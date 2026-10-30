"""See-through の推論スクリプトを、注意計算(attention)を小分けにして実行するラッパー。

T4 などの古い GPU は bf16 の省メモリ attention に対応していないため、
PyTorch は attention の行列をまるごと確保する計算方式に切り替わる(1280px で約20GB)。
ここでは torch.nn.functional.scaled_dot_product_attention を差し替え、
大きな計算だけクエリ方向に分割して実行する。結果は分割しない場合と同じ。

使い方:
  python run_lowmem.py inference/scripts/inference_psd.py --srcp ... (元のスクリプトの引数)
"""
import os
import runpy
import sys

import torch
import torch.nn.functional as F

# 1回の attention で確保してよい行列サイズの目安(バイト)
CHUNK_BYTES = int(float(os.environ.get("ATTN_CHUNK_GB", "1")) * 1024 ** 3)

_orig_sdpa = F.scaled_dot_product_attention


def chunked_sdpa(query, key, value, attn_mask=None, dropout_p=0.0, is_causal=False, scale=None, **kwargs):
    L, S = query.shape[-2], key.shape[-2]
    batch = query.numel() // (L * query.shape[-1])  # バッチ×ヘッド数
    row_bytes = batch * S * query.element_size()
    if is_causal or dropout_p or kwargs or row_bytes * L <= CHUNK_BYTES:
        return _orig_sdpa(query, key, value, attn_mask=attn_mask, dropout_p=dropout_p,
                          is_causal=is_causal, scale=scale, **kwargs)
    step = max(1, CHUNK_BYTES // row_bytes)
    outs = []
    for i in range(0, L, step):
        mask = attn_mask
        if mask is not None and mask.dim() >= 2 and mask.shape[-2] == L:
            mask = mask[..., i:i + step, :]
        outs.append(_orig_sdpa(query[..., i:i + step, :], key, value, attn_mask=mask, scale=scale))
    return torch.cat(outs, dim=-2)


F.scaled_dot_product_attention = chunked_sdpa


if __name__ == "__main__":
    script = sys.argv[1]
    sys.argv = sys.argv[1:]
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    runpy.run_path(script, run_name="__main__")
