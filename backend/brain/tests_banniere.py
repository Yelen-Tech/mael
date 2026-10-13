"""Banniere MAEL : logo aligne, panneau rectangulaire."""
from brain import banniere


def test_logo_aligne():
    # chaque lettre occupe les memes colonnes sur les 6 lignes du logo
    assert len({len(l) for l in banniere.LOGO}) == 1
    assert banniere.LOGO[0].index("█████╗") == banniere.LOGO[1].index("██╔══██╗") + 1


def test_panneau_rectangulaire():
    lignes = banniere.lignes(couleurs=False)
    assert len({len(l) for l in lignes}) == 1
    assert any("Yelen Tech" in l for l in lignes)


def test_degrade_colore_chaque_ligne_du_logo():
    import re
    lignes = banniere.lignes(couleurs=True)
    teintes = [re.search(r"38;5;(\d+)", l) for l in lignes[1:7]]
    assert all(teintes)                       # 6 lignes de logo, 6 teintes
    assert len({t.group(1) for t in teintes}) == 6


def test_sans_couleur_aucun_code_nulle_part():
    assert not any("\033" in l for l in banniere.lignes(couleurs=False))


def test_devoler_ecrit_le_meme_panneau_que_texte():
    import io
    flux = io.StringIO()
    banniere.devoler(flux, couleurs=False, delai=0)
    # devoler() ajoute le saut de ligne initial ; le panneau est identique
    assert flux.getvalue() == "\n" + banniere.texte(couleurs=False)
