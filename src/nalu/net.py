"""Confiance TLS deleguee au magasin de certificats du systeme.

Beaucoup de reseaux d'entreprise dechiffrent le trafic HTTPS avec un proxy dont
l'autorite est installee dans le magasin du poste, mais absente des jeux de racines
publiques embarques par Python. Les appels echouent alors sur
`CERTIFICATE_VERIFY_FAILED`, ce qui ressemble a une panne du fournisseur de donnees
alors que c'est le poste qui filtre.

`truststore` est l'approche recommandee en amont (c'est celle de `pip`) : il branche
le magasin natif du systeme sur le module `ssl`, sans desactiver aucune verification.

Appele explicitement par les points d'entree d'ingestion, jamais a l'import du
paquet : une bibliotheque ne modifie pas la configuration TLS de son hote en douce.
"""

import ssl

_INJECTE = False


def use_system_trust_store() -> bool:
    """Fait verifier les certificats par le magasin du systeme. Idempotent.

    Renvoie `True` si l'injection est active. Ne desactive jamais la verification :
    en cas d'echec, on prefere une erreur TLS franche a un canal non authentifie.
    """
    global _INJECTE
    if _INJECTE:
        return True
    try:
        import truststore
    except ImportError:  # pragma: no cover - `truststore` est une dependance ferme
        return False
    truststore.inject_into_ssl()
    _INJECTE = True
    return True


def default_ssl_context() -> ssl.SSLContext:
    """Contexte TLS a passer a un client qui n'utilise pas le contexte par defaut."""
    use_system_trust_store()
    return ssl.create_default_context()
