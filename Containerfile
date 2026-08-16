ARG BASE_REF=ghcr.io/projectbluefin/bluefin:stable

FROM ${BASE_REF}

ARG BASE_REF
ARG BUILD_PROFILE=base-generic
ARG PURPLEFIN_VERSION=0.0.0-dev

LABEL org.opencontainers.image.title="Purplefin" \
      org.opencontainers.image.description="A custom Bluefin image with composable named profiles" \
      org.opencontainers.image.vendor="declarative-dale" \
      org.opencontainers.image.source="https://github.com/declarative-dale/purplefin" \
      org.opencontainers.image.base.name="${BASE_REF}" \
      org.opencontainers.image.version="${PURPLEFIN_VERSION}"

COPY bootc/ /tmp/purplefin-build/

RUN PURPLEFIN_VERSION="${PURPLEFIN_VERSION}" \
    /tmp/purplefin-build/build/full.sh "${BUILD_PROFILE}" && \
    rm -rf /tmp/purplefin-build && \
    bootc container lint && \
    ostree container commit
