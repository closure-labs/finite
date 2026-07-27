ARG BASE_IMAGE=ghcr.io/projectbluefin/bluefin
ARG BASE_TAG=stable

FROM ${BASE_IMAGE}:${BASE_TAG}

ARG BASE_IMAGE
ARG BASE_TAG
ARG BUILD_PROFILE=base-generic
ARG BUILD_ROLE=base
ARG IMAGE_NAME=purplefin
ARG IMAGE_VENDOR=declarative-dale
ARG PURPLEFIN_OSTREE_LINUX=

LABEL org.opencontainers.image.title="Purplefin"
LABEL org.opencontainers.image.description="A custom Bluefin image with composable named profiles"
LABEL org.opencontainers.image.vendor="${IMAGE_VENDOR}"
LABEL org.opencontainers.image.source="https://github.com/declarative-dale/purplefin"
LABEL org.opencontainers.image.base.name="${BASE_IMAGE}:${BASE_TAG}"
LABEL ostree.linux="${PURPLEFIN_OSTREE_LINUX}"

COPY system_files/ /
COPY manifests/Brewfile /usr/share/purplefin/manifests/Brewfile
COPY manifests/flatpaks.preinstall /usr/share/flatpak/preinstall.d/purplefin.preinstall
COPY build_files/ /tmp/purplefin-build/
COPY profile_files/ /tmp/purplefin-profile-files/

RUN PURPLEFIN_OSTREE_LINUX="${PURPLEFIN_OSTREE_LINUX}" \
    BUILD_ROLE="${BUILD_ROLE}" \
    /tmp/purplefin-build/build.sh "${BUILD_PROFILE}" "${BUILD_ROLE}" && \
    rm -rf /tmp/purplefin-build /tmp/purplefin-profile-files && \
    bootc container lint && \
    ostree container commit
