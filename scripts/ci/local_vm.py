"""Local VM receipts are validation-only and never authorize production promotion."""
import os
import re


DIAGNOSTIC_REF = 'refs/heads/diagnostics/finite-429-brew-preinstall'


def require_runner(profile, env=None):
    env = os.environ if env is None else env
    event, ref = env.get('GITHUB_EVENT_NAME'), env.get('GITHUB_REF', '')
    premerge = event in ('pull_request', 'merge_group') and bool(ref) and ref != 'refs/heads/main'
    diagnostic = event == 'workflow_dispatch' and ref == DIAGNOSTIC_REF and profile == 'finite'
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or not (premerge or diagnostic)):
        raise ValueError('Local VM validation requires an isolated premerge or FINite diagnostic runner')


def validate_context(document, env=None):
    env = os.environ if env is None else env
    require_runner(document.get('profile'), env)
    if env.get('FINITE_LOCAL_VM_VALIDATION') != 'true':
        raise ValueError('Missing local VM validation marker')
    if (document.get('localValidation') is not True
            or document.get('profile') not in ('finite', 'finite-dev')
            or document.get('sourceRevision') != env.get('GITHUB_SHA')
            or not re.fullmatch('[0-9a-f]{40}', document.get('sourceRevision', ''))
            or not re.fullmatch(r'local-image@sha256:[0-9a-f]{64}', document.get('image', ''))
            or not re.fullmatch(r'localhost/finite-validation:[a-z0-9-]+', document.get('installationTag', ''))):
        raise ValueError('Invalid local VM identity')
    return document
