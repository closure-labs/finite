#!/usr/bin/env python3
"""Validate native self-repository references before Actionlint's legacy parser."""
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


def reference(value, root):
    relative = value[2:]
    path = PurePosixPath(relative)
    if (not value.startswith('$/') or str(path) != relative or path.is_absolute()
            or any(part in ('', '.', '..') for part in path.parts)
            or '@' in relative or '\\' in relative):
        raise ValueError('Invalid self-repository reference: ' + value)
    target = root / relative
    if path.parts[:2] == ('.github', 'actions'):
        candidates = [target / 'action.yml', target / 'action.yaml']
    elif path.parts[:2] == ('.github', 'workflows') and path.suffix in ('.yml', '.yaml'):
        candidates = [target]
    else:
        raise ValueError('Self-repository reference must name a declared action or workflow: ' + value)
    if not any(candidate.is_file() for candidate in candidates):
        raise ValueError('Missing self-repository target: ' + value)


def projection(source, root):
    """Change uses scalars only; never rewrite shell text or ignore diagnostics."""
    edits = []
    def values(node, key):
        if isinstance(node, MappingNode):
            for name, value in node.value:
                if isinstance(name, ScalarNode) and name.value == key:
                    yield value
    def uses(node):
        for value in values(node, 'uses'):
            if isinstance(value, ScalarNode) and value.value.startswith('$/'):
                reference(value.value, root)
                start, end = value.start_mark.index, value.end_mark.index
                edits.append((start, end, source[start:end].replace('$/', './', 1)))
    def steps(node):
        for sequence in values(node, 'steps'):
            if isinstance(sequence, SequenceNode):
                for step in sequence.value:
                    uses(step)
    document = yaml.compose(source, Loader=yaml.SafeLoader)
    for jobs in values(document, 'jobs'):
        if isinstance(jobs, MappingNode):
            for _, job in jobs.value:
                uses(job)
                steps(job)
    for runs in values(document, 'runs'):
        steps(runs)
    for start, end, replacement in sorted(set(edits), reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


def lint(root, executable='actionlint'):
    root = Path(root).resolve()
    github = root / '.github'
    # Projection must never follow a checkout-controlled link outside its tree.
    if github.is_symlink() or any(path.is_symlink() for path in github.rglob('*')):
        raise ValueError('Workflow lint refuses symbolic links under .github')
    with tempfile.TemporaryDirectory(prefix='finite-actionlint-') as temporary:
        projected = Path(temporary)
        shutil.copytree(github, projected / '.github')
        (projected / '.git').mkdir()
        for path in (projected / '.github').rglob('*'):
            if path.is_file() and path.suffix in ('.yml', '.yaml'):
                path.write_text(projection(path.read_text(), root))
        workflows = sorted((projected / '.github/workflows').glob('*.y*ml'))
        if not workflows:
            raise ValueError('No workflows to lint')
        result = subprocess.run([executable, *map(str, workflows)], cwd=projected,
                                capture_output=True, text=True, check=False, timeout=120)
        for stream, output in ((sys.stdout, result.stdout), (sys.stderr, result.stderr)):
            print(output.replace(str(projected), str(root)), end='', file=stream)
        return result.returncode if result.returncode >= 0 else 128 - result.returncode


if __name__ == '__main__':
    try:
        sys.exit(lint(Path.cwd()))
    except (ValueError, OSError, yaml.YAMLError, subprocess.SubprocessError) as error:
        print('Workflow lint failed: ' + str(error), file=sys.stderr)
        sys.exit(2)
