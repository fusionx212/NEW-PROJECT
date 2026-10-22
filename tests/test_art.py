import numpy as np

from skysoftly import art


def test_every_art_file_loads():
    for n in ["bedroom", "town", "space", "bunny-sit", "bunny-leap", "bunny-sleep", "star", "moon", "moonbeam", "starfield"]:
        assert art.image(n).size[0] > 300
    for p in art.PLANETS:
        assert art.solid(p, 100).shape[2] == 4


def test_animal_aliases():
    assert art.animal_key("Rabbit") == "bunny"
    assert art.animal_key("bunny") == "bunny"
    assert art.animal_key("dragon") is None


def test_screen_blend_brightens_and_clips_at_edges():
    f = np.full((50, 60, 3), 40.0, np.float32)
    spr = np.full((20, 20, 3), 200.0, np.float32)
    art.screen(f, spr, 0, 0)            # mostly off-frame: must not raise
    art.screen(f, spr, 30, 25)
    assert f[25, 30, 0] > 200 and f.max() <= 255
    assert f[0, 59, 0] == 40.0


def test_over_respects_alpha():
    f = np.zeros((40, 40, 3), np.float32)
    spr = np.zeros((10, 10, 4), np.float32); spr[..., :3] = 255; spr[:5, :, 3] = 255
    art.over(f, spr, 20, 20)
    assert f[16, 20, 0] == 255 and f[23, 20, 0] == 0


def test_ken_burns_maps_focus_to_centre():
    f, to_s, sc = art.ken_burns(art.image("bedroom"), 320, 180, 1.5, 0.5, 0.5)
    assert f.shape == (180, 320, 3)
    x, y = to_s(0.5, 0.5)
    assert abs(x - 160) < 1 and abs(y - 90) < 1


def test_along_path_ends():
    (x0, y0), _ = art.along(art.RIBBON_PATH, 0)
    (x1, y1), _ = art.along(art.RIBBON_PATH, 1)
    assert (x0, y0) == art.RIBBON_PATH[0]
    assert abs(x1 - art.RIBBON_PATH[-1][0]) < 1e-6
