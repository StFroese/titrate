import urllib.request

import astropy.constants as const
import astropy.units as u
import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from gammapy.astro.darkmatter import (
    DarkMatterAnnihilationSpectralModel,
    JFactory,
    profiles,
)
from gammapy.data import Observation, observatory_locations
from gammapy.datasets import MapDataset
from gammapy.irf import load_cta_irfs
from gammapy.makers import MapDatasetMaker, SafeMaskMaker
from gammapy.maps import MapAxis, WcsGeom, WcsNDMap
from gammapy.modeling.models import (
    FoVBackgroundModel,
    Models,
    SkyModel,
    TemplateSpatialModel,
)


@pytest.fixture(scope="module")
def irfs(tmp_path_factory):
    tmpdir = tmp_path_factory.mktemp("tmp-")

    url = (
        "https://github.com/gammapy/gammapy-extra/raw/"
        "master/datasets/cta-1dc/caldb/data/cta/1dc/bcf/South_z20_50h/irf_file.fits"
    )

    urllib.request.urlretrieve(url, f"{tmpdir}/irf_file.fits")

    irfs = load_cta_irfs(f"{tmpdir}/irf_file.fits")

    return irfs


@pytest.fixture(scope="module")
def observation(irfs):
    livetime = 50 * u.hr
    pointing = SkyCoord(0, 0, unit="deg", frame="galactic")
    location = observatory_locations["cta_south"]
    obs = Observation.create(
        pointing=pointing, livetime=livetime, irfs=irfs, location=location
    )

    return obs


@pytest.fixture(scope="module")
def energy_axes():
    energy_reco = MapAxis.from_edges(
        np.logspace(-1.0, 1.0, 10), unit="TeV", name="energy", interp="log"
    )
    energy_axis_true = MapAxis.from_energy_bounds(
        "0.03 TeV", "300 TeV", nbin=20, per_decade=True, name="energy_true"
    )
    migra_axis = MapAxis.from_bounds(0.5, 2, nbin=150, node_type="edges", name="migra")

    return {"true": energy_axis_true, "reco": energy_reco, "migra": migra_axis}


@pytest.fixture(scope="module")
def geometry3d(observation, energy_axes):
    geom = WcsGeom.create(
        skydir=observation.pointing.fixed_icrs,
        width=(4, 4),
        binsz=0.02,
        frame="galactic",
        axes=[energy_axes["reco"]],
    )

    return geom


@pytest.fixture(scope="module")
def geometry2d(observation):
    geom = WcsGeom.create(
        skydir=observation.pointing.fixed_icrs,
        width=(4, 4),
        binsz=0.02,
        frame="galactic",
    )

    return geom


@pytest.fixture(scope="module")
def ursa_major_ii_profile():
    rhos = (
        10**-1.1331 * const.M_sun.to(u.GeV, equivalencies=u.mass_energy()) / u.pc**3
    )
    rs = 10**3.6317 * u.pc

    profile = profiles.NFWProfile(r_s=rs, rho_s=rhos)
    profile.DISTANCE_GC = 32 * u.kpc

    return profile


@pytest.fixture(scope="module")
def dm_models(observation, geometry2d, ursa_major_ii_profile):
    jfactory = JFactory(
        geom=geometry2d,
        profile=ursa_major_ii_profile,
        distance=ursa_major_ii_profile.DISTANCE_GC,
    )
    jfactor = jfactory.compute_differential_jfactor()
    jfact_map = WcsNDMap(geom=geometry2d, data=jfactor.value, unit=jfactor.unit)
    spatial_model = TemplateSpatialModel(jfact_map, normalize=False)

    spectral_model = DarkMatterAnnihilationSpectralModel(mass=50 * u.TeV, channel="b")

    model_simu = SkyModel(
        spatial_model=spatial_model,
        spectral_model=spectral_model,
        name="darkmatter",
    )

    bkg_model = FoVBackgroundModel(dataset_name="foo")

    models = Models([model_simu, bkg_model])

    return models


@pytest.fixture(scope="module")
def measurement_dataset(geometry3d, energy_axes, observation, dm_models):
    from titrate.utils import copy_models_to_dataset

    maker = MapDatasetMaker(selection=["exposure", "background", "psf", "edisp"])
    maker_safe_mask = SafeMaskMaker(methods=["offset-max"], offset_max=4.0 * u.deg)

    empty_measurement = MapDataset.create(
        geometry3d,
        energy_axis_true=energy_axes["true"],
        migra_axis=energy_axes["migra"],
        name="measurement",
    )

    measurement_dataset = maker.run(empty_measurement, observation)
    measurement_dataset = maker_safe_mask.run(measurement_dataset, observation)

    copy_models_to_dataset(dm_models, measurement_dataset)

    measurement_dataset.fake(random_state=42)

    return measurement_dataset


@pytest.fixture(scope="module")
def nosignal_dataset(geometry3d, energy_axes, observation, dm_models):
    from titrate.utils import copy_models_to_dataset

    maker = MapDatasetMaker(selection=["exposure", "background", "psf", "edisp"])
    maker_safe_mask = SafeMaskMaker(methods=["offset-max"], offset_max=4.0 * u.deg)

    empty_measurement = MapDataset.create(
        geometry3d,
        energy_axis_true=energy_axes["true"],
        migra_axis=energy_axes["migra"],
        name="measurement",
    )

    nosignal_dataset = maker.run(empty_measurement, observation)
    nosignal_dataset = maker_safe_mask.run(nosignal_dataset, observation)

    copy_models_to_dataset(dm_models, nosignal_dataset)
    nosignal_dataset.models.parameters["scale"].value = 0

    nosignal_dataset.fake(random_state=1337)

    return nosignal_dataset


@pytest.fixture(scope="module")
def asimov_dataset(geometry3d, energy_axes, observation, dm_models):
    from titrate.datasets import AsimovMapDataset
    from titrate.utils import copy_models_to_dataset

    maker = MapDatasetMaker(selection=["exposure", "background", "psf", "edisp"])
    maker_safe_mask = SafeMaskMaker(methods=["offset-max"], offset_max=4.0 * u.deg)

    empty_asimov = AsimovMapDataset.create(
        geometry3d,
        energy_axis_true=energy_axes["true"],
        migra_axis=energy_axes["migra"],
        name="asimov",
    )

    asimov_dataset = maker.run(empty_asimov, observation)
    asimov_dataset = maker_safe_mask.run(asimov_dataset, observation)

    copy_models_to_dataset(dm_models, asimov_dataset)

    asimov_dataset.fake()

    return asimov_dataset
