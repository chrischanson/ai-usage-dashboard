# linux_scripts tests

Run the rip-compressor regression tests with:

```bash
./projects/linux_scripts/tests/test-rip-compressor.sh
```

The `fakes/` directory contains small `ffmpeg` and `ffprobe` stand-ins. They let
the tests verify command generation and media probing behavior without requiring
real DVD/Blu-ray files or doing any actual encoding.

