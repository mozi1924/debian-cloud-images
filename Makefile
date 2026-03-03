# path to the config space shoud be absolute, see fai.conf(5)

DESTDIR = .

ifneq (,${SEED_UUID})
seed_uuid_opt=--seed-uuid ${SEED_UUID}
endif

ifeq (,${VERSION})
VERSION=$(shell date '+%Y%m%d%H%M')
endif

SOURCE_DATE_EPOCH ?= $(shell date +%s)
export SOURCE_DATE_EPOCH

help:
	@echo "To run this makefile, run:"
	@echo "   make image_<DIST>_<CLOUD>_<ARCH>"
	@echo "  WHERE <DIST> is bullseye, bookworm, trixie, sid"
	@echo "    And <CLOUD> is azure, ec2, gce, generic, genericcloud, nocloud"
	@echo "    And <ARCH> is amd64, arm64, ppc64el, riscv64, s390x"
	@echo "Set DESTDIR= to write images to given directory."

image_%:
	@echo "SOURCE_DATE_EPOCH=$(SOURCE_DATE_EPOCH)"
	@echo "SEED_UUID=$(SEED_UUID)"
	@echo "VERSION=$(VERSION)"
	umask 022; \
	./bin/debian-cloud-images build-mkosi \
	  $(subst _, ,$*) \
	  --build-id manual \
	  --version $(VERSION) \
	  --override-name $@ \
	  --output $(DESTDIR) \
	  $(seed_uuid_opt) \
	  $(NOOP)

oci_%:
	umask 022; \
	./bin/debian-cloud-images build-mkosi \
	  $(subst _, ,$*) \
	  --build-id manual \
	  --version $(VERSION) \
	  --override-name $@ \
	  --output $(DESTDIR) \
	  --output-format oci \
	  $(seed_uuid_opt) \
	  $(NOOP)


clean:
	rm -rf mkosi.output oci_*.* image_*.* mkosi.conf.d/.mkosi-private mkosi.conf.d/partitions
