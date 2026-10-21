"""PR VM receipts are validation-only and never authorize production promotion."""
import os
import re


def validate_context(document, env=None):
    env = os.environ if env is None else env
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or env.get('GITHUB_EVENT_NAME') not in ('pull_request', 'merge_group')
            or env.get('GITHUB_REF') == 'refs/heads/main'
            or env.get('FINITE_LOCAL_VM_VALIDATION') != 'true'):
        raise ValueError('Local VM validation requires an isolated premerge runner')
    if (document.get('localValidation') is not True
            or document.get('profile') not in ('finite', 'finite-dev')
            or document.get('sourceRevision') != env.get('GITHUB_SHA')
            or not re.fullmatch('[0-9a-f]{40}', document.get('sourceRevision', ''))
            or not re.fullmatch(r'local-image@sha256:[0-9a-f]{64}', document.get('image', ''))
            or not re.fullmatch(r'localhost/finite-validation:[a-z0-9-]+', document.get('installationTag', ''))):
        raise ValueError('Invalid local VM identity')
    return document
