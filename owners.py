# Copyright (c) 2010 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A database of OWNERS files."""

import re


# If this is present by itself on a line, this means that everyone can review.
EVERYONE = '*'


# Recognizes 'X@Y' email addresses. Very simplistic.
BASIC_EMAIL_REGEXP = r'^[\w\-\+\%\.]+\@[\w\-\+\%\.]+$'


class SyntaxErrorInOwnersFile(Exception):
  def __init__(self, path, line, msg):
    super(SyntaxErrorInOwnersFile, self).__init__((path, line, msg))
    self.path = path
    self.line = line
    self.msg = msg

  def __str__(self):
    if self.msg:
      return "%s:%d syntax error: %s" % (self.path, self.line, self.msg)
    else:
      return "%s:%d syntax error" % (self.path, self.line)


class Database(object):
  """A database of OWNERS files for a repository.

  This class allows you to find a suggested set of reviewers for a list
  of changed files, and see if a list of changed files is covered by a
  list of reviewers."""

  def __init__(self, root, fopen, os_path):
    """Args:
      root: the path to the root of the Repository
      open: function callback to open a text file for reading
      os_path: module/object callback with fields for 'abspath', 'dirname',
          'exists', and 'join'
    """
    self.root = root
    self.fopen = fopen
    self.os_path = os_path

    # TODO: Figure out how to share the owners email addr format w/
    # tools/commit-queue/projects.py, especially for per-repo whitelists.
    self.email_regexp = re.compile(BASIC_EMAIL_REGEXP)

    # Mapping of owners to the paths they own.
    self.owned_by = {EVERYONE: set()}

    # Mapping of paths to authorized owners.
    self.owners_for = {}

    # Set of paths that stop us from looking above them for owners.
    # (This is implicitly true for the root directory).
    self.stop_looking = set([''])

  def ReviewersFor(self, files):
    """Returns a suggested set of reviewers that will cover the set of files.

    files is a set of paths relative to (and under) self.root."""
    self._CheckPaths(files)
    self._LoadDataNeededFor(files)
    return self._CoveringSetOfOwnersFor(files)

  def FilesAreCoveredBy(self, files, reviewers):
    """Returns whether every file is owned by at least one reviewer."""
    return not self.FilesNotCoveredBy(files, reviewers)

  def FilesNotCoveredBy(self, files, reviewers):
    """Returns the set of files that are not owned by at least one reviewer."""
    self._CheckPaths(files)
    self._CheckReviewers(reviewers)
    if not reviewers:
      return files

    self._LoadDataNeededFor(files)
    files_by_dir = self._FilesByDir(files)
    covered_dirs = self._DirsCoveredBy(reviewers)
    uncovered_files = []
    for d, files_in_d in files_by_dir.iteritems():
      if not self._IsDirCoveredBy(d, covered_dirs):
        uncovered_files.extend(files_in_d)
    return set(uncovered_files)

  def _CheckPaths(self, files):
    def _isunder(f, pfx):
      return self.os_path.abspath(self.os_path.join(pfx, f)).startswith(pfx)
    assert all(_isunder(f, self.os_path.abspath(self.root)) for f in files)

  def _CheckReviewers(self, reviewers):
    """Verifies each reviewer is a valid email address."""
    assert all(self.email_regexp.match(r) for r in reviewers)

  def _FilesByDir(self, files):
    dirs = {}
    for f in files:
      dirs.setdefault(self.os_path.dirname(f), []).append(f)
    return dirs

  def _DirsCoveredBy(self, reviewers):
    dirs = self.owned_by[EVERYONE]
    for r in reviewers:
      dirs = dirs | self.owned_by.get(r, set())
    return dirs

  def _StopLooking(self, dirname):
    return dirname in self.stop_looking

  def _IsDirCoveredBy(self, dirname, covered_dirs):
    while not dirname in covered_dirs and not self._StopLooking(dirname):
      dirname = self.os_path.dirname(dirname)
    return dirname in covered_dirs

  def _LoadDataNeededFor(self, files):
    for f in files:
      dirpath = self.os_path.dirname(f)
      while not dirpath in self.owners_for:
        self._ReadOwnersInDir(dirpath)
        if self._StopLooking(dirpath):
          break
        dirpath = self.os_path.dirname(dirpath)

  def _ReadOwnersInDir(self, dirpath):
    owners_path = self.os_path.join(self.root, dirpath, 'OWNERS')
    if not self.os_path.exists(owners_path):
      return

    lineno = 0
    for line in self.fopen(owners_path):
      lineno += 1
      line = line.strip()
      if line.startswith('#'):
        continue
      if line == 'set noparent':
        self.stop_looking.add(dirpath)
        continue
      if self.email_regexp.match(line) or line == EVERYONE:
        self.owned_by.setdefault(line, set()).add(dirpath)
        self.owners_for.setdefault(dirpath, set()).add(line)
        continue
      raise SyntaxErrorInOwnersFile(owners_path, lineno, line)

  def _CoveringSetOfOwnersFor(self, files):
    # TODO(dpranke): implement the greedy algorithm for covering sets, and
    # consider returning multiple options in case there are several equally
    # short combinations of owners.
    every_owner = set()
    for f in files:
      dirname = self.os_path.dirname(f)
      while dirname in self.owners_for:
        every_owner |= self.owners_for[dirname]
        if self._StopLooking(dirname):
          break
        dirname = self.os_path.dirname(dirname)
    return every_owner
