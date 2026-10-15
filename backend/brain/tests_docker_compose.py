"""docker-compose.yml ne doit jamais contredire images.lock — 16/10/2026.

Revue externe : images en « latest » (dont nmap, ecarte pour sa licence) et
identifiants PostgreSQL par defaut, base exposee sur le reseau.
    ./venv/Scripts/python.exe -m pytest brain/tests_docker_compose.py -q
"""
import json
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
COMPOSE = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
VERROU = json.loads((Path(__file__).parent / "tools" / "images.lock")
                    .read_text(encoding="utf-8"))


def test_outils_figes_par_l_empreinte_du_verrou():
    outils = re.findall(r"^\s*image:\s*(\S+)", COMPOSE, re.M)
    assert not [i for i in outils if i.endswith(":latest")]
    for image in outils:
        nom = image.split("@")[0].split(":")[0]
        if nom in VERROU:
            assert image == VERROU[nom], f"{nom} differe de images.lock"
    assert "nmap" not in COMPOSE.split("nmap n'est pas embarque")[0]


def test_pas_d_identifiants_par_defaut_ni_de_port_ouvert_au_reseau():
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?" in COMPOSE
    for port in re.findall(r"ports:\s*\[([^\]]*)\]", COMPOSE):
        assert all(p.strip(' "').startswith("127.0.0.1:")
                   for p in port.split(",")), port
