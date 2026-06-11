# SPDX-License-Identifier: GPL-2.0-or-later

from fnmatch import fnmatch

import tarfile


# given a tar archive, split it into two archives such that the first
# contains members matching the given patterns, and the second
# contains the members that don't match
def split_tar(in_path, outA_path, outB_path, patterns):
    tin = tarfile.open(name=in_path, mode="r|*")

    toutA = tarfile.open(name=outA_path, mode="w|")
    toutB = tarfile.open(name=outB_path, mode="w|")

    try:
        for ti in tin:
            name = ti.name
            for p in patterns:
                if fnmatch(name, p):
                    tout = toutA
                else:
                    tout = toutB

            if ti.isreg():
                src = tin.extractfile(ti)
                tout.addfile(ti, fileobj=src)
            else:
                # dirs, symlinks, hardlinks, devices, etc. have no payload stream
                tout.addfile(ti)

    finally:
        toutA.close()
        toutB.close()
        tin.close()
