"""
Contains a bunch of model utility functions, used to construct models while trying to minimise copy and pasteing code.
"""
import jax
import jax.numpy as jnp

import numpyro
import numpyro.distributions as dist


def create_intervention_prior(nCMs, prior_type="normal"):
    """
    Create alpha_i variables, which are the intervention effections.

    :param nCMs: Number of CMs
    :param prior_type: either 'trunc_normal' or 'normal'
    :return: alpha_i numpyro RV
    """
    if prior_type == "trunc_normal":
        alpha_i = numpyro.sample(
            "alpha_i", dist.TruncatedNormal(low=-0.1, loc=jnp.zeros(nCMs), scale=0.2)
        )
    elif prior_type == "normal":
        alpha_i = numpyro.sample("alpha_i", dist.Normal(loc=jnp.zeros(nCMs), scale=0.1))
    else:
        raise ValueError(
            "Intervention effect prior must take a value in [trunc_normal]"
        )
    return alpha_i


def get_discrete_renewal_transition_from_projmat(gi_projmat):
    """
    Create discrete renewal transition function, used by `jax.lax.scan`

    :param gi_projmat: gi projection matrix

    :return: Discrete Renewal Transition function, with relevant GI parameters
    """

    def discrete_renewal_transition(infections, R_with_noise_tuple):
        # infections is an nR x total_padding size array of infections in the previous
        # total_padding days.
        R, inf_noise = R_with_noise_tuple
        new_infections = infections @ gi_projmat
        new_infections = jax.ops.index_update(
            new_infections,
            jax.ops.index[:, -1],
            jnp.multiply(new_infections[:, -1], R) + inf_noise,
        )
        return new_infections, new_infections[:, -1]

    return discrete_renewal_transition


def get_discrete_renewal_transition(ep):
    """
    Create discrete renewal transition function, used by `jax.lax.scan`

    :param ep: EpidemiologicalParameters() objective

    :return: Discrete Renewal Transition function, with relevant GI parameters
    """

    def discrete_renewal_transition(infections, R_with_noise_tuple):
        # infections is an nR x total_padding size array of infections in the previous
        # total_padding days.
        R, inf_noise = R_with_noise_tuple
        new_infections = infections @ ep.GI_projmat
        new_infections = jax.ops.index_update(
            new_infections,
            jax.ops.index[:, -1],
            jnp.multiply(new_infections[:, -1], R) + inf_noise,
        )
        return new_infections, new_infections[:, -1]

    return discrete_renewal_transition


def observe_cases_deaths(data, expected_cases, expected_deaths):
    """
    Observation model

    :param data: PreprocessedData Object
    :param expected_cases: Expected Cases - nRs x nDs array
    :param expected_deaths: Expected Deaths - nRs x nDs array
    """
    psi_cases = numpyro.sample("psi_cases", dist.HalfNormal(5))
    psi_deaths = numpyro.sample("psi_deaths", dist.HalfNormal(5))

    with numpyro.handlers.mask(mask=jnp.logical_not(data.new_cases.mask)):
        observed_cases = numpyro.sample(
            "observed_cases",
            dist.GammaPoisson(concentration=psi_cases, rate=psi_cases / expected_cases),
            obs=data.new_cases.data,
        )

    with numpyro.handlers.mask(mask=jnp.logical_not(data.new_deaths.mask)):
        observed_deaths = numpyro.sample(
            "observed_deaths",
            dist.GammaPoisson(
                concentration=psi_deaths, rate=psi_deaths / expected_deaths
            ),
            obs=data.new_deaths.data,
        )


def setup_dr_infection_model(data, ep):
    """
    Setup discrete renewal infection model.

    :param data: data (used for shape)
    :param ep: epidemiological parameters (also used for shape)
    :return: (init_infections, total_infections, infection_noise, seeding_padding) tuple. Init infections is an array of
    size GI_vector x nRs which is scanned over. Total infections is an empty nRs x nDs + seeding_padding array.
    Infection noise is an nRs x nDs vector used for additive infection niose. seeding_padding is the number of days that
    we seed infections for.
    """
    seeding_padding = 7
    total_padding = ep.GIv.size - 1

    seeding = numpyro.sample("seeding", dist.LogNormal(jnp.zeros((data.nRs, 1)), 5.0))
    init_infections = jnp.zeros((data.nRs, total_padding))
    init_infections = jax.ops.index_add(
        init_infections,
        jax.ops.index[:, -seeding_padding:],
        jnp.repeat(seeding, seeding_padding, axis=-1),
    )

    total_infections = jnp.zeros((data.nRs, seeding_padding + data.nDs))

    infection_noise_scale = numpyro.sample("infection_noise_scale", dist.HalfNormal(3))
    infection_noise = numpyro.sample(
        "infection_noise",
        dist.HalfNormal(infection_noise_scale * jnp.ones((data.nRs, data.nDs))),
    )

    return init_infections, total_infections, infection_noise, seeding_padding


def get_output_delay_transition(seeding_padding, data):
    def output_delay_transition(loop_carry, scan_slice):
        # this scan function scans over local areas, using their country specific delay, rather than over days
        # we don't need a loop carry, so we just return 0 and ignore the loop carry!
        (
            future_cases,
            future_deaths,
            country_cases_delay,
            country_deaths_delay,
        ) = scan_slice
        expected_cases = jnp.convolve(future_cases, country_cases_delay, mode="full")[
            seeding_padding : data.nDs + seeding_padding
        ]
        expected_deaths = jnp.convolve(
            future_deaths, country_deaths_delay, mode="full"
        )[seeding_padding : data.nDs + seeding_padding]

        return 0.0, (expected_cases, expected_deaths)

    return output_delay_transition