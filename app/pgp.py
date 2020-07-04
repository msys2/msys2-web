from pgpdump import BinaryData
from pgpdump.utils import PgpdumpException
from datetime import datetime
from typing import NamedTuple
import struct
import binascii


KNOWN_KEYS = {
    "5F92EFC1A47D45A1": "Alexey Pavlov",
    "4DF3B7664CA56930": "Ray Donnelly",
    "D595C9AB2C51581E": "Martell Malone",
    "974C8BE49078F532": "David Macek",
    "FA11531AA0AA7F57": "Christoph Reiter",
}


class Signature(NamedTuple):
    keyid: str
    date: datetime

    @property
    def url(self) -> str:
        return "http://pool.sks-keyservers.net/pks/lookup?op=vindex&fingerprint=on&search=0x" + self.keyid

    @property
    def name(self) -> str:
        return KNOWN_KEYS.get(self.keyid.upper(), "Unknown")


class SigError(Exception):
    pass


def parse_signature(sig_data: bytes) -> Signature:
    date = None
    keyid = None

    try:
        parsed = BinaryData(sig_data)
    except PgpdumpException as e:
        raise SigError(e)

    for x in parsed.packets():
        if x.raw == 2:
            for sub in x.subpackets:
                if sub.subtype == 2:
                    date = datetime.utcfromtimestamp(struct.unpack('>I', sub.data)[0])
                if sub.subtype == 16:
                    keyid = binascii.hexlify(sub.data).decode()

    if keyid is None:
        raise SigError("keyid missing")
    if date is None:
        raise SigError("date missing")

    return Signature(keyid, date)
