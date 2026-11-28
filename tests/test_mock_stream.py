"""The mock headset's sample has what the real one's has: the 8 band powers, a raw waveform over the tick, and
attention and meditation that follow the beta and alpha shares of the power."""
import random

from app.eeg import mock_stream_v2
from app.eeg.band_spec import BAND_KEYS
from app.eeg.mock_stream_v2 import MockEEGStream


def test_a_sample_has_the_bands_a_waveform_and_the_esense_values():
    stream = MockEEGStream()
    stream.start()
    for _ in range(40):
        sample = stream.read_sample()
        assert list(sample) == ["timestamp", *BAND_KEYS, "raw_eeg_waveform", "attention", "meditation"]
        assert all(sample[band] >= 0.0 for band in BAND_KEYS)
        assert len(sample["raw_eeg_waveform"]) == 64
        assert all(0.0 <= sample[key] <= 100.0 and isinstance(sample[key], float) for key in ("attention", "meditation"))


def test_attention_follows_the_beta_share_and_meditation_the_alpha_share():
    random.seed(1)
    beta = {"alpha1": 100.0, "alpha2": 100.0, "beta1": 5000.0, "beta2": 5000.0, "theta": 100.0}
    alpha = {"alpha1": 5000.0, "alpha2": 5000.0, "beta1": 100.0, "beta2": 100.0, "theta": 100.0}
    (beta_attention, beta_meditation), (alpha_attention, alpha_meditation) = (
        mock_stream_v2._attention_meditation(beta), mock_stream_v2._attention_meditation(alpha))
    assert beta_attention > 40 > beta_meditation and alpha_meditation > 50 > alpha_attention  # 60 and 70 at full share


def test_the_waveform_is_as_strong_as_the_band_powers():
    random.seed(2)
    stream = MockEEGStream()
    stream.start()
    quiet = stream._waveform(1.0, dict.fromkeys(BAND_KEYS, 0.0))
    loud = stream._waveform(1.0, dict.fromkeys(BAND_KEYS, 10000.0))
    assert max(map(abs, quiet)) < 10 < max(map(abs, loud))  # the noise alone is 2 sd; 8 bands of amplitude 100
