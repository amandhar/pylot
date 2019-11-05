from collections import deque
import pickle
import threading
import time

from erdos.data_stream import DataStream
from erdos.op import Op
from erdos.utils import setup_csv_logging, setup_logging, time_epoch_ms

from pylot.perception.detection.utils import visualize_no_colors_bboxes
from pylot.utils import is_camera_stream, is_obstacles_stream, is_deep_sort_logs_stream


class ObjectTrackerOp(Op):
    def __init__(self,
                 name,
                 output_stream_name,
                 tracker_type,
                 flags,
                 log_file_name=None,
                 csv_file_name=None):
        super(ObjectTrackerOp, self).__init__(name)
        self._flags = flags
        self._logger = setup_logging(self.name, log_file_name)
        self._csv_logger = setup_csv_logging(self.name + '-csv', csv_file_name)
        self._output_stream_name = output_stream_name
        try:
            if tracker_type == 'cv2':
                from pylot.perception.tracking.cv2_tracker import MultiObjectCV2Tracker
                self._tracker = MultiObjectCV2Tracker(self._flags)
            elif tracker_type == 'da_siam_rpn':
                from pylot.perception.tracking.da_siam_rpn_tracker import MultiObjectDaSiamRPNTracker
                self._tracker = MultiObjectDaSiamRPNTracker(self._flags)
            elif tracker_type == 'deep_sort':
                from pylot.perception.tracking.deep_sort_tracker import MultiObjectDeepSORTTracker
                self._tracker = MultiObjectDeepSORTTracker(self._flags)
            else:
                self._logger.fatal(
                    'Unexpected tracker type {}'.format(tracker_type))
        except ImportError:
            self._logger.fatal('Error importing {}'.format(tracker_type))
        # True when the tracker is ready to update bboxes.
        self._ready_to_update = False
        self._ready_to_update_timestamp = None
        self._to_process = deque()
        self._logs = deque()
        self._lock = threading.Lock()

    @staticmethod
    def setup_streams(input_streams,
                      output_stream_name,
                      camera_stream_name=None):
        input_streams.filter(is_obstacles_stream).add_callback(
            ObjectTrackerOp.on_objects_msg)
        # Select camera input streams.
        camera_streams = input_streams.filter(is_camera_stream)
        if camera_stream_name:
            # Select only the camera the operator is interested in.
            camera_streams = camera_streams.filter_name(camera_stream_name)
        # Register a callback on the camera input stream.
        camera_streams.add_callback(ObjectTrackerOp.on_frame_msg)
        #input_streams.filter(is_deep_sort_logs_stream).add_callback(
        #   ObjectTrackerOp.on_log_msg)
        return [DataStream(name=output_stream_name)]

    #def on_log_msg(self, msg):
    #    self._logs.append(msg)

    def on_frame_msg(self, msg):
        """ Invoked when a FrameMessage is received on the camera stream."""
        self._lock.acquire()
        start_time = time.time()
        assert msg.encoding == 'BGR', 'Expects BGR frames'
        frame = msg.frame
        # Store frames so that they can be re-processed once we receive the
        # next update from the detector.
        self._to_process.append((msg.timestamp, frame))
        # Track if we have a tracker ready to accept new frames.
        if self._ready_to_update:
            self.__track_bboxes_on_frame(frame, msg.timestamp, False)
        # Get runtime in ms.
        runtime = (time.time() - start_time) * 1000
        self._csv_logger.info('{},{},"{}",{}'.format(time_epoch_ms(),
                                                     self.name, msg.timestamp,
                                                     runtime))
        self._lock.release()

    def on_objects_msg(self, msg):
        """ Invoked when detected objects are received on the stream."""
        self._lock.acquire()
        self._ready_to_update = False
        self._logger.info("Received {} bboxes for {}".format(
            len(msg.detected_objects), msg.timestamp))
        # Remove frames that are older than the detector update.
        while len(self._to_process
                  ) > 0 and self._to_process[0][0] < msg.timestamp:
            self._logger.info("Removing stale {} {}".format(
                self._to_process[0][0], msg.timestamp))
            self._to_process.popleft()
        
        #while len(self._logs) > 0 and self._logs[0][0] < msg.timestamp:
        #    self._logger.info("Removing stale {} {}".format(
        #        self._logs[0][0], msg.timestamp))
        #    self._logs.popleft()
        # bboxes = self.__get_highest_confidence_pedestrian(msg.detected_objects)
        # Track all pedestrians.
        bboxes, ids = self.__get_pedestrians(msg.detected_objects)
        if len(bboxes) > 0:
            if len(self._to_process) > 0:
                # Found the frame corresponding to the bounding boxes.
                (timestamp, frame) = self._to_process.popleft()
                #(log_timestamp, logs) = self._logs.popleft()
                assert timestamp == msg.timestamp# == log_timestamp
                # Re-initialize trackers.
                logs = construct_deep_sort_logs(bboxes, ids)
                self.__initialize_trackers(frame, bboxes, msg.timestamp, logs)
                self._logger.info('Trackers have {} frames to catch-up'.format(
                    len(self._to_process)))
                for (timestamp, frame) in self._to_process:
                    if self._ready_to_update:
                        self.__track_bboxes_on_frame(frame, timestamp, True)
            else:
                self._logger.info(
                    'Received bboxes update {}, but no frame to process'.
                    format(msg.timestamp))
        self._lock.release()

    def execute(self):
        self.spin()

    def create_deep_sort_logs(bboxes, ids):
        lines = []
        for i in range(len(bboxes)):
            bbox = bboxes[i]
            obj_id = ids[i]
            (x1, y1), (x2, y2) = bbox
            bbox_x, bbox_y = x1, y1
            bbox_w, bbox_h = x2 - x1, y2 - y1
            log_line = "{},{},{},{},{},{},{},{},{},{}\n".format(
                0, obj_id, bbox_x, bbox_y, bbox_w, bbox_h, 1.0, -1, -1, -1) # timestamp is 0 here
            lines.append(log_line)
        return lines

    def checkpoint(self, timestamp):
        """ Invoked by ERDOS when the operator must checkpoint state.

        The checkpoint should include all the state up to and including
        timestamp.

        Args:
            timestamp: The timestamp at which the checkpoint is taken.
        """
        # We can't checkpoint the tracker itself because it has internal state.
        state = [self._ready_to_update_timestamp,
                 self._ready_to_update,
                 self._to_process]
        file_name = '{}{}.checkpoint'.format(
            self._name, timestamp.coordinates[0])
        pickle.dump(state, open(file_name, 'wb'))
        return file_name

    def restore(self, timestamp, checkpoint):
        """ Invoked by ERDOS when the operator must restore state.

        The method rebuilds the state from the checkpoint.
        Args:
            timestamp: The timestamp the checkpoint was taken at.
            checkpoint: The checkpoint was taken at timestamp.
        """
        checkpoint = pickle.load(open(checkpoint, 'rb'))
        self._ready_to_update_timestamp = checkpoint[0]
        self._ready_to_update = checkpoint[1]
        self._to_process = checkpoint[2]

    def __get_highest_confidence_pedestrian(self, detected_objs):
        max_confidence = 0
        max_corners = None
        for detected_obj in detected_objs:
            if (detected_obj.label == 'person' and
                detected_obj.confidence > max_confidence):
                max_corners = detected_obj.corners
                max_confidence = detected_obj.confidence
        if max_corners:
            return [max_corners]
        else:
            return []

    def __get_pedestrians(self, detector_objs):
        bboxes = []
        ids = []
        for detected_obj in detector_objs:
            if detected_obj.label == 'person':
                bboxes.append(detected_obj.corners)
                ids.append(detected_obj.obj_id)
        return bboxes, ids

    def __initialize_trackers(self, frame, bboxes, timestamp, deep_sort_logs=None):
        self._ready_to_update = True
        self._ready_to_update_timestamp = timestamp
        self._logger.info('Restarting trackers at frame {}'.format(timestamp))
        self._tracker.reinitialize(frame, bboxes, deep_sort_logs)

    def __track_bboxes_on_frame(self, frame, timestamp, catch_up):
        self._logger.info('Processing frame {}'.format(timestamp))
        # Sequentually update state for each bounding box.
        ok, bboxes = self._tracker.track(frame)
        if not ok:
            self._logger.error(
                'Tracker failed at timestamp {} last ready_to_update at {}'.
                format(timestamp, self._ready_to_update_timestamp))
            # The tracker must be reinitialized.
            self._ready_to_update = False
        else:
            if self._flags.visualize_tracker_output and not catch_up:
                #visualize_no_colors_bboxes(self.name, timestamp, frame, bboxes)
                for bbox, bbox_id in zip(bboxes, bbox_ids):
                    frame = self.visualize_on_img(frame, bbox, bbox_id)
                cv2.imshow(frame)

    def visualize_on_img(self, image_np, bbox, bbox_id_text):
        """ Annotate the image with the bounding box of the obstacle."""
        txt_font = cv2.FONT_HERSHEY_SIMPLEX
        (xmin, xmax, ymin, ymax) = bbox
        txt_size = cv2.getTextSize(bbox_id_text, txt_font, 0.5, 2)[0]
        color = [128, 0, 0]
        # Show bounding box.
        cv2.rectangle(image_np, (xmin, ymin), (xmax, ymax), color, 2)
        # Show text.
        cv2.rectangle(image_np,
                      (xmin, ymin - txt_size[1] - 2),
                      (xmin + txt_size[0], ymin - 2), color, -1)
        cv2.putText(image_np, bbox_id_text, (xmin, ymin - 2),
                    txt_font, 0.5, (0, 0, 0), thickness=1,
                    lineType=cv2.LINE_AA)
        return image_np
