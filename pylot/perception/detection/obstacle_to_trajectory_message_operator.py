import erdos

from absl import flags
from collections import defaultdict, deque
from pylot.perception.messages import ObstacleTrajectoriesMessage


class ObstacleToTrajectoryMessageOperator(erdos.Operator):
    def __init__(self, obstacles_stream, obstacles_trajectory_strea, flags, trajectory_length=None):
        obstacles_stream.add_callback(self.on_obstacles_msg,
                                      [obstacles_trajectory_stream])
        if trajectory_length:
            self._trajectory_length = trajectory_length
        elif flags.prediction_num_past_steps:
            self._trajectory_length = flags.prediction_num_past_steps
        self.past_n_obstacles_messages = defaultdict(deque(maxlen=self._trajectory_length))
        self._logger = erdos.utils.setup_logging(self.config.name,
                                                 self.config.log_file_name)
        self._flags = flags

    @staticmethod
    def connect(obstacles_stream):
        """Connects the operator to other streams.

        Args:
            obstacles_stream (:py:class:`erdos.ReadStream`): The stream on which
                obstacles from a detector are received.

        Returns:
            :py:class:`erdos.WriteStream`: Stream on which the operator sends
            :py:class:`~pylot.perception.messages.ObstacleTrajectoriesMessage` messages.
        """
        obstacles_trajectory_stream = erdos.WriteStream()
        return [obstacles_trajectory_stream]

    @erdos.profile_method()
    def on_obstacles_msg(self, msg, obstacles_trajectory_stream):
        for obstacle in msg.obstacles:
            self.past_n_obstacles_messages[obstacle.id].append(obstacle)
        obstacle_trajectories = []
        for obstacle_id, obstacles in self.past_n_obstacles_messages.items():
            if len(obstacles) >= self._trajectory_length:
                trajectory = [obstacle.transform for obstacle in obstacles]
                most_recent_obstacle = obstacles[-1]
                obstacle_trajectory = ObstacleTrajectory(most_recent_obstacle.label,
                                                         most_recent_obstacle.id,
                                                         most_recent_obstacle.id.bounding_box,
                                                         trajectory)
                obstacle_trajectories.append(obstacle_trajectory)
        obstacles_trajectory_stream.send(
            ObstacleTrajectoriesMessage(msg.timestamp, obstacle_trajectories))

