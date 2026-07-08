"""AES helpers for Tuya Smart Lock password encryption."""

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


def decrypt_ticket_key(ticket_key: str, access_secret: str) -> bytes:
    """Decrypt the ticket_key returned by Tuya using our access_secret."""
    key = access_secret[:16].encode("utf-8")
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.decrypt(bytes.fromhex(ticket_key))[:16]


def encrypt_password(password: str, real_key: bytes) -> str:
    """Encrypt a plaintext lock password with the real device key."""
    cipher = AES.new(real_key, AES.MODE_ECB)
    padded = pad(password.encode(), AES.block_size)
    return cipher.encrypt(padded).hex().upper()
