ARG BUILD_BASE
FROM ${BUILD_BASE} AS build
COPY source.tar.gz /source.tar.gz
COPY source-lock.json /source-lock.json
COPY build-runtime.sh /build-runtime.sh
RUN mkdir /src && tar -xf /source.tar.gz --strip-components=1 -C /src && rm /source.tar.gz
RUN dnf -y install 'dnf5-command(builddep)' rpm-build gcc gcc-c++ \
      libselinux-devel glib2-devel fuse3-devel python3 \
    && dnf -y builddep /src/contrib/packaging/bootc.spec && dnf clean all
WORKDIR /src
# No build credentials are passed to this container. Cargo.lock authenticates
# crate checksums and immutable git revisions; compilation runs offline below.
RUN cargo fetch --locked
ENV CARGO_BUILD_JOBS=1 CARGO_INCREMENTAL=0 CARGO_PROFILE_RELEASE_LTO=false \
    CARGO_PROFILE_RELEASE_DEBUG=0 CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16 \
    RUSTFLAGS="-C link-arg=-lselinux"
RUN --network=none bash /build-runtime.sh
FROM scratch AS packages
COPY --from=build /out/ /
