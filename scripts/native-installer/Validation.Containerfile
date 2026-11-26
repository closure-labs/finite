ARG NATIVE_ROOT
FROM ${NATIVE_ROOT}
COPY validation-guest.py /usr/libexec/finite/validation-guest.py
COPY serial_records.py /usr/libexec/finite/serial_records.py
COPY validation-guest.service /usr/lib/systemd/system/validation-guest.service
# Only the disposable lifecycle baseline supplies the older, pinned EFI binary.
COPY loader/ /usr/lib/systemd/boot/efi/
# These signed-in arguments and the observation unit exist only in VM payloads.
RUN printf '%s\n' 'kargs = ["rw", "console=ttyS0,115200n8", "rd.plymouth=0", "plymouth.enable=0"]' > /usr/lib/bootc/kargs.d/00-finite-native.toml \
    && systemctl enable validation-guest.service
