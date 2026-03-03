#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

# Partition UUIDs are stored in various places within the images, including the
# grub configuration and fstab, as well as in the partition/filesystem metadata
# itself.
# Note that not all images will use all UUIDs generated here.
outfile="${ARTIFACTDIR}/partitions"

exec > "$outfile"
echo PARTUUID_ROOT=$(uuid -v 5 "$SEED_UUID" PARTUUID_ROOT)
echo FSUUID_ROOT=$(uuid -v 5 "$SEED_UUID" FSUUID_ROOT)
echo DIRHASH_ROOT=$(uuid -v 5 "$SEED_UUID" DIRHASH_ROOT)
echo GPT_TABLE_UUID=$(uuid -v 5 "$SEED_UUID" GPT_TABLE_UUID)

case "$DISTRIBUTION_ARCHITECTURE" in
    ppc64el)
        echo PARTUUID_PREP=$(uuid -v 5 "$SEED_UUID" PARTUUID_PREP)
        ;;
    arm64|amd64)
        echo PARTUUID_ESP=$(uuid -v 5 "$SEED_UUID" PARTUUID_ESP)
        echo -n "ESP_VFAT_SERIAL="
        python3 -c "import random; random.seed(\"$SEED_UUID\"); print(random.randint(0, 99999999))"
        # only actually meaningful on amd64...
        echo PARTUUID_BIOS=$(uuid -v 5 "$SEED_UUID" PARTUUID_BIOS)
        ;;
esac

. "${outfile}"

if [ -z "$PARTUUID_ROOT" ]; then
    echo "UUID generation failed" >&2
    exit 1
fi

echo "Generated build-specific UUIDs:" >&2
cat "${outfile}" >&2
