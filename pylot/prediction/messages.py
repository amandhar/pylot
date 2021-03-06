import erdos


class PredictionMessage(erdos.Message):
    """Message class to be used to send obstacle predictions.

    Args:
        timestamp (:py:class:`erdos.timestamp.Timestamp`): The timestamp of
            the message.
        predictions (list(:py:class:`~pylot.prediction.obstacle_prediction.ObstaclePrediction`)):
            Obstacle predictions.

    Attributes:
        predictions (list(:py:class:`~pylot.prediction.obstacle_prediction.ObstaclePrediction`)):
            Obstacle predictions.
    """
    def __init__(self, timestamp, predictions):
        super(PredictionMessage, self).__init__(timestamp, None)
        self.predictions = predictions

    def __str__(self):
        return 'PredictionMessage(timestamp: {}, predictions: {})'.format(
            self.timestamp, self.predictions)
