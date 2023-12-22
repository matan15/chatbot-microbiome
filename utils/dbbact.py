from typing import List
import requests as req
from pprint import pprint

def get_dbbact_response(sequences: List):
    response = req.get("https://devwww.dbbact.org/get_sequences_stats", json={"sequences": sequences})
    response.raise_for_status()
    return response.json()