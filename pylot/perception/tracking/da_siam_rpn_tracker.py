import cv2
import numpy as np
import torch

from skimage.measure import compare_ssim
from sklearn.utils.linear_assignment_ import linear_assignment

from DaSiamRPN.code.net import SiamRPNvot
from DaSiamRPN.code.run_SiamRPN import SiamRPN_init, SiamRPN_track

from pylot.perception.detection.utils import DetectedObject
from pylot.perception.tracking.multi_object_tracker import MultiObjectTracker

MAX_TRACKER_AGE = 5


class SingleObjectDaSiamRPNTracker(object):
    def __init__(self, frame, bbox, siam_net, obj_id=-1):
        self.bbox = bbox
        self.obj_id = obj_id
        self.missed_det_updates = 0
        width = bbox[1] - bbox[0]
        height = bbox[3] - bbox[2]
        target_pos = np.array([(bbox[0] + bbox[1]) / 2.0,
                               (bbox[2] + bbox[3]) / 2.0])
        target_size = np.array([width, height])
        self._tracker = SiamRPN_init(frame, target_pos, target_size, siam_net)

    def track(self, frame):
        self._tracker = SiamRPN_track(self._tracker, frame)
        target_pos = self._tracker['target_pos']
        target_sz = self._tracker['target_sz']
        self.bbox = (int(target_pos[0] - target_sz[0] / 2.0),
                     int(target_pos[0] + target_sz[0] / 2.0),
                     int(target_pos[1] - target_sz[1] / 2.0),
                     int(target_pos[1] + target_sz[1] / 2.0))
        return DetectedObject(self.bbox, 0, "")


class MultiObjectDaSiamRPNTracker(MultiObjectTracker):
    def __init__(self, flags):
        # Initialize the siam network.
        self._siam_net = SiamRPNvot()
        self._siam_net.load_state_dict(
            torch.load(flags.da_siam_rpn_model_path))
        self._siam_net.eval().cuda()
        self._trackers = []

    def reinitialize(self, frame, bboxes, confidence_scores, ids):
        # Create matrix of similarities between detection and tracker bboxes
        cost_matrix = self._create_hungarian_cost_matrix(frame, bboxes)
        # Run sklearn linear assignment (Hungarian Algo) with matrix
        assignments = linear_assignment(cost_matrix)

        updated_trackers = []
        # Add matched trackers to updated_trackers
        for bbox_idx, tracker_idx in assignments:
            updated_trackers.append(
                SingleObjectDaSiamRPNTracker(frame,
                                             bboxes[bbox_idx],
                                             self._siam_net,
                                             self._trackers[tracker_idx].obj_id))
        # Add 1 to age of any unmatched trackers, filter old ones
        if len(self._trackers) > len(bboxes):
            for i, tracker in enumerate(self._trackers):
                if i not in assignments[:, 1]:
                    tracker.missed_det_updates += 1
                    if tracker.missed_det_updates < MAX_TRACKER_AGE:
                         updated_trackers.append(tracker)
        # Create new trackers for new bboxes
        elif len(bboxes) > len(self._trackers):
            for i, bbox in enumerate(bboxes):
                if i not in assignments[:, 0]:
                    updated_trackers.append(
                        SingleObjectDaSiamRPNTracker(frame, bbox, self._siam_net, ids[i]))
        
        self._trackers = updated_trackers

    def _create_hungarian_cost_matrix(self, frame, bboxes):
        # Create cost matrix with shape (num_bboxes, num_trackers)
	cost_matrix = [[0 for _ in range(len(self._trackers))] for __ in range(len(bboxes))]
        for i, bbox in enumerate(bboxes):
            for j, tracker in enumerate(self._trackers):
                tracker_bbox = tracker.bbox
                # Get crops from frame
                print(bbox, tracker_bbox)
                bbox_crop = frame[bbox[2]:bbox[3], bbox[0]:bbox[1]]
                tracker_bbox_crop = frame[tracker_bbox[2]:tracker_bbox[3], tracker_bbox[0]:tracker_bbox[1]]
                # Resize larger crop to same shape as smaller one
                bbox_area = np.prod(bbox_crop.shape[:2])
                tracker_bbox_area = np.prod(tracker_bbox_crop.shape[:2])
                if bbox_area < tracker_bbox_area:
                    print(tracker_bbox_crop.shape)
                    tracker_bbox_crop = cv2.resize(tracker_bbox_crop,
                                                   bbox_crop.shape[:2][::-1], # cv2 needs width, then height
                                                   interpolation = cv2.INTER_AREA)
                else:
                    print(bbox_crop.shape)
                    bbox_crop = cv2.resize(bbox_crop,
                                           tracker_bbox_crop.shape[:2][::-1], # cv2 needs width, then height
                                           interpolation = cv2.INTER_AREA)
                # Use SSIM as metric for crop similarity, assign to matrix
                print(bbox_crop.shape, tracker_bbox_crop.transpose((1, 0, 2)).shape)
                cost_matrix[i][j] = compare_ssim(bbox_crop, tracker_bbox_crop, multichannel=True)
        return np.array(cost_matrix)

