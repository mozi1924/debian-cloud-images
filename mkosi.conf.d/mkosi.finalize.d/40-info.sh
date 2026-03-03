#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later

set -euE
shopt -s extglob nullglob

ROOTCMD=mkosi-chroot
${ROOTCMD} dpkg -s > "${OUTPUTDIR}/${IMAGE_ID}.dpkg-status"

exec > ${OUTPUTDIR}/${IMAGE_ID}.info

function show() {
  if [ ${#@} -ge 1 ]; then
    tail -vn +1 "$@" | sed -e "s:${BUILDROOT}::"
  fi
}

echo "SEED_UUID=$SEED_UUID"
echo "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH"
echo "VERSION=$CLOUD_RELEASE_VERSION"

echo "--- CLOUD RELEASE ---"
cat ${BUILDROOT}/etc/cloud-release
echo "--- END CLOUD RELEASE --- "
echo "--- APT SOURCES.LIST ---"
if [ -n "${BUILDROOT}" ] ; then
	if [ -r ${BUILDROOT}/etc/apt/sources.list ] ; then
		show ${BUILDROOT}/etc/apt/sources.list
	fi
	if [ -d "${BUILDROOT}/etc/apt/sources.list.d" ] ; then
		for i in $(find ${BUILDROOT}/etc/apt/sources.list.d -type f) ; do
			show ${i}
		done
	fi
fi
echo "--- END APT SOURCES.LIST ---"
echo "--- APT PREFERENCES ---"
if [ -n "${BUILDROOT}" ] ; then
	if [ -r "${BUILDROOT}/etc/apt/preferences" ] ; then
		show ${BUILDROOT}/etc/apt/preferences
	fi
	if [ -d "${BUILDROOT}/etc/apt/preferences.d" ] ; then
		for i in $(find ${BUILDROOT}/etc/apt/preferences.d -type f) ; do
			show ${i}
		done
	fi
fi
echo "--- END APT PREFERENCES ---"
echo "--- FILES CHANGED ---"
debsums -r ${BUILDROOT} -a -c | sed -e "s:^${BUILDROOT}::" || [ $? != 2 ]
echo "--- END FILES CHANGED ---"
echo "--- PACKAGES ---"
${ROOTCMD} dpkg -l
echo "--- END PACKAGES ---"
