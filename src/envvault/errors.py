"""Errores esperados: la CLI los muestra sin traza."""


class EnvVaultError(Exception):
    """Error de uso o de datos que se explica al usuario."""


class VaultNotFound(EnvVaultError):
    """No existe el fichero de la bóveda."""


class VaultLocked(EnvVaultError):
    """La bóveda está bloqueada y no se puede pedir la contraseña."""


class WrongPassword(EnvVaultError):
    """Contraseña o clave de recuperación incorrecta."""


class CorruptVault(EnvVaultError):
    """El fichero de la bóveda está dañado o no es de EnvVault."""


class NotFound(EnvVaultError):
    """No existe el proyecto, entorno o secreto indicado."""
