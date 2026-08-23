{pkgs}:
pkgs.writeShellApplication {
  name = "finite-image-sign";
  runtimeInputs = with pkgs; [coreutils cosign];
  text = ''
    : "''${COSIGN_IDENTITY:?COSIGN_IDENTITY is required}"
    : "''${DIGEST:?DIGEST is required}"
    : "''${IMAGE_REF:?IMAGE_REF is required}"

    cosign_command="''${FINITE_COSIGN:-cosign}"
    retry_delay="''${FINITE_COSIGN_RETRY_DELAY_SECONDS:-5}"
    sign_attempts="''${FINITE_COSIGN_SIGN_ATTEMPTS:-2}"
    verify_attempts="''${FINITE_COSIGN_VERIFY_ATTEMPTS:-6}"

    [[ "''${DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
      echo "Invalid image digest: ''${DIGEST}" >&2
      exit 2
    }
    [[ "''${retry_delay}" =~ ^[0-9]+$ ]] || {
      echo "FINITE_COSIGN_RETRY_DELAY_SECONDS must be a non-negative integer" >&2
      exit 2
    }
    [[ "''${sign_attempts}" =~ ^[1-9][0-9]*$ ]] || {
      echo "FINITE_COSIGN_SIGN_ATTEMPTS must be a positive integer" >&2
      exit 2
    }
    [[ "''${verify_attempts}" =~ ^[1-9][0-9]*$ ]] || {
      echo "FINITE_COSIGN_VERIFY_ATTEMPTS must be a positive integer" >&2
      exit 2
    }

    immutable_image="''${IMAGE_REF}@''${DIGEST}"
    verify_image() {
      "''${cosign_command}" verify \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        --certificate-identity "''${COSIGN_IDENTITY}" \
        "''${immutable_image}" >/dev/null
    }

    # A retry of the same immutable publication must not add another signature.
    if verify_image 2>/dev/null; then
      echo "The immutable image already has a trusted signature" >&2
      exit 0
    fi

    signed=false
    for ((attempt = 1; attempt <= sign_attempts; attempt += 1)); do
      if "''${cosign_command}" sign --yes "''${immutable_image}"; then
        signed=true
        break
      fi
      echo "Cosign signing attempt ''${attempt}/''${sign_attempts} failed" >&2
      if (( attempt < sign_attempts && retry_delay > 0 )); then
        sleep "''${retry_delay}"
      fi
    done
    [[ "''${signed}" == true ]] || {
      echo "Cosign signing failed after ''${sign_attempts} attempts" >&2
      exit 1
    }

    verified=false
    for ((attempt = 1; attempt <= verify_attempts; attempt += 1)); do
      if verify_image; then
        verified=true
        break
      fi
      echo "Cosign verification attempt ''${attempt}/''${verify_attempts} failed" >&2
      if (( attempt < verify_attempts && retry_delay > 0 )); then
        sleep "''${retry_delay}"
      fi
    done
    [[ "''${verified}" == true ]] || {
      echo "Cosign verification failed after ''${verify_attempts} attempts" >&2
      exit 1
    }
  '';
}
