import logging

from .vantage_point import VantagePoint

logger = logging.getLogger(__name__)


class VantagePointManager:
    """
    A class to manage vantage points.
    """

    def __init__(self) -> None:
        self.vantage_points: dict[str, VantagePoint] = {}

    def add_vps(self, vps: dict[str, VantagePoint]) -> None:
        """
        A method to add vantage points to the manager.
       
        :param: vps: dict[str, VantagePoint] - a dictionary of vantage points to add.
        :return: None
        """
        self.vantage_points.update(vps)
        logger.info("VantagePointManager registered %d VPs (total now: %d)", len(vps), len(self.vantage_points))

    def get_vps(self, stable: bool = True) -> dict[str, VantagePoint]:  
        """
        A method to get all vantage points.
        
        :param: stable: bool - whether to get the stable vantage points.
        :return: dict[str, VantagePoint] - a dictionary of vantage points.
        """
        return {k: v for k, v in self.vantage_points.items() if (v.metadata.is_stable if stable else True)}

    def get_vps_for_platform(self, platform: str, stable: bool = True) -> dict[str, VantagePoint]:
        """
        A method to get all vantage points for a platform.
      
        :param: platform: str - the platform of the vantage points.
        :param: stable: bool - whether to get the stable vantage points.
        :return: dict[str, VantagePoint] - a dictionary of vantage points.
        """
        return {k: v for k, v in self.vantage_points.items() if v.platform == platform and (v.metadata.is_stable if stable else True)}

    def get_vp_names(self, stable: bool = True) -> list[str]:
        """
        A method to get all vantage point names.
    
        :param: stable: bool - whether to get the stable vantage points.
        :return: list[str] - a list of vantage point names.
        """
        return [k for k, v in self.vantage_points.items() if (v.metadata.is_stable if stable else True)]

    def get_vp_names_of_platform(self, platform: str, stable: bool = True) -> list[str]:
        """
        A method to get all vantage point names for a platform.
     
        :param: platform: str - the platform of the vantage points.
        :param: stable: bool - whether to get the stable vantage points.
        :return: list[str] - a list of vantage point names.
        """
        return [k for k, v in self.vantage_points.items() if v.platform == platform and (v.metadata.is_stable if stable else True)]

    def get_vp_by_name(self, name: str,  ) -> VantagePoint:
        """
        A method to get a vantage point by name.
     
        :param: name: str - the name of the vantage point.
        :return: VantagePoint - the vantage point.
        """
        return self.vantage_points[name]

    def get_anchor_vps(self, stable: bool = True) -> dict[str, VantagePoint]:
        """
        A method to get all anchor vantage points.
     
        :param: stable: bool - whether to get the stable anchor vantage points.
        :return: list[VantagePoint] - a list of anchor vantage points.
        """
        return {k: v for k, v in self.vantage_points.items() if v.metadata.is_anchor and( v.metadata.is_stable if stable else True)}

    def get_anchor_vp_names(self, stable: bool = True) -> list[str]:
        """
        A method to get all anchor vantage point names.
    
        :param: stable: bool - whether to get the stable anchor vantage points.
        :return: list[str] - a list of anchor vantage point names.
        """
        return [k for k, v in self.vantage_points.items() if v.metadata.is_anchor and (v.metadata.is_stable if stable else True)]




