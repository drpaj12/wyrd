# viz: the 3D provenance viewer (Heimdall III)

The 3D provenance viewer that was part of Wyrd III (`o3viz`) is now its own project, Heimdall III:
<https://github.com/drpaj12/heimdallIII>. Its manual, with screenshots, is `docs/user/viz.md` there, and the
viewer has its own help page (press `?`).

Install it next to Wyrd:

    pip install 'wyrd[viz]'
    # or: pip install git+https://github.com/drpaj12/heimdallIII.git

`wyrd viz export|serve|site ...` then forwards to `heimdall export|serve|site ...` with the same arguments as
before (`site` is new: it builds a static site of many benchmarks). Without Heimdall installed, `wyrd viz` prints
how to install it and exits 2.
