from enum import Enum

class MeasurementStatus(Enum):
    """
    A enum to represent the status of a measurement.
    - CREATED: The measurement has been created but not scheduled yet.
    - RUNNING: The measurement is running and results are being polled from the driver each polling interval.
    - FINISHED: The measurement has completed successfully and all vantage points have returned a result.
    - FAILED: At least one vantage point has return -1.0 RTT.
    - TIMEOUT: At least one vantage point has not returned a result within the measurement timeout.
    - ACQUIRING: The measurement is acquiring vantage points.
    - UNACQUIRED: The measurement has not acquired any vantage points.
    """
    CREATED = "created"
    RUNNING = "running" 
    FINISHED = "finished"
    FAILED = "failed"
    TIMEOUT = "timeout"    
    ACQUIRING = "acquiring"
    UNACQUIRED = "unacquired"
    ACQUIRED = "acquired"