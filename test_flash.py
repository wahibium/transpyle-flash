"""Tests of FLASH transpilation."""

import datetime
import logging
import os
import pathlib
import subprocess
import unittest

import git
from transpyle.general import CodeReader, CodeWriter
from transpyle.fortran import FortranParser, FortranAstGeneralizer, Fortran2008Unparser

import common
from common import _run_and_check

logging.basicConfig()

_LOG = logging.getLogger(__name__)

_HERE = pathlib.Path(__file__).parent.resolve()

common._NOW = datetime.datetime.now()


def fortran_to_fortran(path: pathlib.Path):
    """Transpile Fortran to Fortran, using Python AST as intermediate (generalized) format.

    Reader reads the code.
    Parser creates a Fortran-specific AST.
    Generalizer transforms it into AST that can be easily processed and unparsed into many outputs.
    Unparsers creates Fortran code from the same generalized AST.
    Original file is moved from "name.ext" to "name.ext.bak", unless the backup already exists.
    Writer writes the transpiled file to where the original file was.
    """
    reader = CodeReader()
    parser = FortranParser()
    generalizer = FortranAstGeneralizer()
    unparser = Fortran2008Unparser()
    writer = CodeWriter(path.suffix)

    code = reader.read_file(path)
    fortran_ast = parser.parse(code, path)
    tree = generalizer.generalize(fortran_ast)
    fortran_code = unparser.unparse(tree)

    backup_path = path.with_suffix(path.suffix + '.bak')
    if not backup_path.is_file():
        pathlib.Path.rename(path, backup_path)
    writer.write_file(fortran_code, path)


class FlashTests(unittest.TestCase):

    root_path = None
    source_path = pathlib.Path('source')
    setup_cmd = ['./setup', '-site', 'spack']
    make_cmd = ['make']
    run_cmd = ['mpirun', '-np', '2', './flash4']
    clean_repo = True

    timeout = None  # type: int

    def setUp(self):
        if type(self) is FlashTests:
            self.skipTest('...')
        repo = git.Repo(str(pathlib.Path(_HERE, self.root_path)), search_parent_directories=True)
        repo_path = pathlib.Path(repo.working_dir)
        self.assertIn(str(_HERE), str(repo_path), msg=(repo_path, _HERE, repo))
        self.assertNotEqual(repo_path, _HERE, msg=(repo_path, _HERE, repo))
        repo_is_dirty = repo.is_dirty(untracked_files=True)
        if repo_is_dirty and self.clean_repo:
            repo.git.clean(f=True, d=True, x=True)
            repo.git.reset(hard=True)
            _LOG.warning('Repository %s has been cleaned and reset.', repo)

    def run_transpyle(self, transpiled_paths):
        absolute_transpiled_paths = [pathlib.Path(_HERE, self.root_path, self.source_path, path)
                                     for path in transpiled_paths]
        if not absolute_transpiled_paths:
            return
        all_failed = True
        for path in absolute_transpiled_paths:
            self.assertTrue(path.is_file())
            with self.subTest(path=path):
                fortran_to_fortran(path)
                all_failed = False
        if all_failed:
            self.fail(msg='Failed to transpile any of the files {}.'
                      .format(absolute_transpiled_paths))

    def _run_and_check(self, cmd, wd, log_filename_prefix):
        _run_and_check(cmd, wd, test_name=self.id(), phase_name=log_filename_prefix)

    def run_flash(self, flash_args, object_path: pathlib.Path = None, quick: bool = False):
        if object_path is None:
            object_path = pathlib.Path('object')
        absolute_flash_path = pathlib.Path(_HERE, self.root_path)
        absolute_object_path = pathlib.Path(_HERE, self.root_path, object_path)
        if isinstance(flash_args, str):
            flash_args = flash_args.split(' ')
        flash_setup_cmd = self.setup_cmd + flash_args
        # flash_setup_cmd[0] = str(pathlib.Path(_HERE, self.root_path, flash_setup_cmd[0]))
        flash_make_cmd = self.make_cmd
        flash_run_cmd = self.run_cmd

        something_wrong = True
        with self.subTest(flash_path=absolute_flash_path, setup_cmd=flash_setup_cmd,
                          make_cmd=flash_make_cmd, run_cmd=flash_run_cmd):
            if quick and absolute_object_path.is_dir():
                _LOG.warning('Skipping setup & build -- objdir "%s" already exists.', object_path)
            else:
                _LOG.warning('Setting up FLASH...')
                self._run_and_check(flash_setup_cmd, absolute_flash_path, 'setup')
                _LOG.warning('Setup succeeded.')

                _LOG.warning('Building FLASH...')
                self._run_and_check(flash_make_cmd, absolute_object_path, 'make')
                _LOG.warning('Build succeeded.')

            try:
                run_result = subprocess.run(' '.join(flash_run_cmd), shell=True,
                                            cwd=str(absolute_object_path), timeout=self.timeout)
                self.assertEqual(run_result.returncode, 0, msg=run_result)
            except subprocess.TimeoutExpired:
                _LOG.warning('Test %s takes a long time.', self.id(), exc_info=1)
            something_wrong = False
        if something_wrong:
            self.fail('FLASH setup, build, or run failed.')

    def run_problem(self, transpiled_paths, flash_args, object_path=None, pre_verify=True,
                    quick: bool = False):
        assert not (transpiled_paths and quick)
        if pre_verify:
            self.run_flash(flash_args, object_path, quick)
        self.run_transpyle(transpiled_paths)
        self.run_flash(flash_args, object_path, quick)

    def run_sod_problem(self, transpiled_paths, **kwargs):
        args = 'Sod -auto -2d'
        self.run_problem(transpiled_paths, args, **kwargs)

    def run_mhd_rotor_problem(self, transpiled_paths, **kwargs):
        args = \
            'magnetoHD/CurrentSheet -auto -2d -objdir=mhdrotor -gridinterpolation=native -debug'
        self.run_problem(transpiled_paths, args, object_path=pathlib.Path('mhdrotor'), **kwargs)


class NewTests(FlashTests):

    run_cmd = ['./flash4']
    clean_repo = False

    quick = True

    @classmethod
    def setUpClass(cls):
        cls.root_path = pathlib.Path('flash-subset', 'FLASH4.4')

    def test_sod_uniform_grid_2d(self):
        paths = []
        args = 'Sod -auto -2d +nofbs -parfile=test_UG_nofbs_2d.par -objdir=sodug2d -debug'
        args += ' +noio'
        objdir = 'sodug2d'
        self.run_problem(paths, args, object_path=pathlib.Path(objdir), pre_verify=False, quick=True)

    def test_sod_uniform_grid_3d(self):
        paths = []
        args = 'Sod -auto -3d +nofbs -parfile=test_UG_nofbs_3d.par -objdir=sodug3d -debug'
        args += ' +noio'
        objdir = 'sodug3d'
        self.run_problem(paths, args, object_path=pathlib.Path(objdir), pre_verify=False, quick=True)

    def test_sod_paramesh_2d(self):
        paths = []
        args = 'Sod -2d -auto +Mode1 -objdir=sodpm2d -debug'
        args += ' +noio'
        objdir = 'sodpm2d'
        self.run_problem(paths, args, object_path=pathlib.Path(objdir), pre_verify=False, quick=True)

    def test_sod_paramesh_3d(self):
        paths = []
        args = 'Sod -3d -auto +Mode1 -objdir=sodpm3d -debug'
        args+= ' +noio'
        objdir = 'sodpm3d'
        self.run_problem(paths, args, object_path=pathlib.Path(objdir), pre_verify=False, quick=True)

    def test_sod_amrex_2d(self):
        paths = []
        args = 'Sod -2d -auto +Mode3 -objdir=sodamrex2d -debug'
        # args += ' +noio'
        objdir = 'sodamrex2d'
        self.run_problem(paths, args, object_path=pathlib.Path(objdir), pre_verify=False, quick=True)

    def test_sod_amrex_3d(self):
        paths = []
        args = 'Sod -3d -auto +Mode3 -objdir=sodamrex3d -debug'
        args += ' +noio'
        objdir = 'sodamrex3d'
        self.run_problem(paths, args, object_path=pathlib.Path(objdir), pre_verify=False, quick=True)

    def test_cellular_2d(self):
        paths = []
        args = 'Cellular -auto -2d +a13 -objdir=cellular2d'
        objdir = 'cellular2d'
        self.run_problem(paths, args, object_path=pathlib.Path(objdir), pre_verify=False, quick=True)

    def test_cellular_3d(self):
        paths = []
        args = 'Cellular -auto -3d +a13 -objdir=cellular3d'
        objdir = 'cellular3d'
        self.run_problem(paths, args, object_path=pathlib.Path(objdir), pre_verify=False, quick=True)


class FlashSubsetTests(FlashTests):

    run_cmd = ['./flash4']

    @classmethod
    def setUpClass(cls):
        cls.root_path = pathlib.Path('flash-subset', 'FLASH4.4')

    def test_hy_hllUnsplit_sod_mode1(self):
        """First test case proposed for transpilation."""
        paths = ['physics/Hydro/HydroMain/simpleUnsplit/HLL/hy_hllUnsplit.F90']
        # args = \
        #    'Sod -auto -2d -unit=Grid/GridAmrexLike' \
        #    ' -unit=physics/Hydro/HydroMain/simpleUnsplit/HLL -parfile=demo_simplehydro_2d.par'
        args = 'Sod -auto -2d +Mode1'
        self.run_problem(paths, args, pre_verify=True)

    def test_hy_hllUnsplit_sod_mode3(self):
        """First test case proposed for transpilation."""
        paths = ['physics/Hydro/HydroMain/simpleUnsplit/HLL/hy_hllUnsplit.F90']
        args = 'Sod -auto -2d +Mode3'
        self.run_problem(paths, args, pre_verify=True)

    def test_hy_hllUnsplit_sedov_mode1(self):
        """."""
        paths = ['physics/Hydro/HydroMain/simpleUnsplit/HLL/hy_hllUnsplit.F90']
        args = 'Sedov -auto -2d +Mode1'
        self.run_problem(paths, args, pre_verify=True)

    def test_hy_hllUnsplit_sedov_mode3(self):
        """."""
        paths = ['physics/Hydro/HydroMain/simpleUnsplit/HLL/hy_hllUnsplit.F90']
        args = 'Sedov -auto -2d +Mode3'
        self.run_problem(paths, args, pre_verify=True)


class Flash45Tests(FlashTests):

    @classmethod
    def setUpClass(cls):
        cls.root_path = pathlib.Path('flash-4.5')

    # @unittest.expectedFailure
    def test_hy_uhd_getFaceFlux(self):
        """Issue #1."""
        paths = ['physics/Hydro/HydroMain/unsplit/hy_uhd_getFaceFlux.F90']
        self.run_sod_problem(paths)

    def test_hy_8wv_interpolate(self):
        """Issue #2."""
        paths = ['physics/Hydro/HydroMain/split/MHD_8Wave/hy_8wv_interpolate.F90']
        self.run_mhd_rotor_problem(paths)

    # @unittest.expectedFailure
    def test_hy_8wv_fluxes(self):
        """Issue #3."""
        paths = ['physics/Hydro/HydroMain/split/MHD_8Wave/hy_8wv_fluxes.F90']
        self.run_mhd_rotor_problem(paths)

    def test_eos_idealGamma(self):
        """Issue #4."""
        paths = ['physics/Eos/EosMain/Gamma/eos_idealGamma.F90']
        self.run_mhd_rotor_problem(paths)

    def test_hy_8wv_sweep(self):
        """Issue #5."""
        paths = ['physics/Hydro/HydroMain/split/MHD_8Wave/hy_8wv_sweep.F90']
        self.run_mhd_rotor_problem(paths)

    def test_hy_uhd_DataReconstructNormalDir_MH(self):
        """Issue #6."""
        paths = ['physics/Hydro/HydroMain/unsplit/hy_uhd_DataReconstructNormalDir_MH.F90']
        self.run_sod_problem(paths)

    def test_hy_uhd_upwindTransverseFlux(self):
        """Issue #7."""
        paths = ['physics/Hydro/HydroMain/unsplit/hy_uhd_upwindTransverseFlux.F90']
        self.run_sod_problem(paths)

    @unittest.expectedFailure  # interface
    def test_hy_uhd_TVDslope(self):
        """Issue #8."""
        paths = ['physics/Hydro/HydroMain/unsplit/hy_uhd_TVDslope.F90']
        self.run_sod_problem(paths)

    def test_hy_uhd_Roe(self):
        """Issue #9."""
        paths = ['physics/Hydro/HydroMain/unsplit/hy_uhd_Roe.F90']
        self.run_sod_problem(paths)

    @unittest.skip('...')
    def test_(self):
        paths = []
        args = ''
        self.run_problem(paths, args)
