from abc import ABC, abstractmethod
from clipscore.ingest.dto import RawCampaign, CampaignUpsert


class BaseIngester(ABC):
    source_name: str = ""

    @abstractmethod
    def fetch(self) -> list[RawCampaign]:
        ...

    @abstractmethod
    def normalize(self, raw: RawCampaign) -> CampaignUpsert:
        ...
