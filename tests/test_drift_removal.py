import inspect

import cftime
import numpy as np
import pytest
import xarray as xr

from cmip6_preprocessing.drift_removal import (
    _construct_cfdate,
    calculate_drift,
    find_date_idx,
    remove_trend,
    replace_time,
    unify_time,
)


# I copied this from a PR I made to parcels a while back.
# Is there a more elegant way to parse these from cftime?
def _get_cftime_datetimes():
    cftime_calendars = tuple(
        x[1].__name__ for x in inspect.getmembers(cftime._cftime, inspect.isclass)
    )
    cftime_datetime_names = [ca for ca in cftime_calendars if "Datetime" in ca]
    return cftime_datetime_names


all_cftime_calendars = [
    getattr(cftime, cf_datetime)(1990, 1, 1).calendar
    for cf_datetime in _get_cftime_datetimes()
]


@pytest.mark.parametrize("source_calendar", all_cftime_calendars)
@pytest.mark.parametrize("target_calendar", all_cftime_calendars)
@pytest.mark.parametrize(
    "ref_idx, start_date",
    [
        (-12, "2001-01-01"),
        (12, "1999-01-01"),
        (1, "1999-12-01"),
        (11, "1999-02-01"),
        (13, "1998-12-01"),
        (-13, "2001-02-01"),
    ],
)
def test_replace_time(source_calendar, target_calendar, ref_idx, start_date):
    nt = 10
    timename = "time"
    time = xr.cftime_range(
        "2000-01-01", periods=nt, freq="1MS", calendar=source_calendar
    )
    ds = xr.DataArray(
        np.random.rand(nt), dims=timename, coords={timename: time}
    ).to_dataset(name="test")

    # simply replace with a different calendar
    time_replaced = xr.DataArray(
        xr.cftime_range("2000-01-01", periods=nt, freq="1MS", calendar=target_calendar),
        dims=["time"],
    )
    ds_replaced = replace_time(ds, calendar=target_calendar)
    xr.testing.assert_allclose(time_replaced, ds_replaced.time)

    # shift time with reference date before the actual data (e.g. for forced runs)
    time_shifted = xr.DataArray(
        xr.cftime_range(start_date, periods=nt, freq="1MS", calendar=target_calendar),
        dims=["time"],
    )
    ds_shifted = replace_time(
        ds, calendar=target_calendar, ref_idx=ref_idx, ref_date="2000-01-01"
    )
    xr.testing.assert_allclose(time_shifted, ds_shifted.time)


def test_replace_time_error_other_freq():
    # Check that a useful error is raised if the input frequency is not monthly
    nt = 10
    timename = "time"
    time = xr.cftime_range("2000-01-01", periods=nt, freq="1MS")
    ds = xr.DataArray(
        np.random.rand(nt), dims=timename, coords={timename: time}
    ).to_dataset(name="test")
    with pytest.raises(ValueError) as einfo:
        ds_new = replace_time(ds, freq="1DS")


@pytest.mark.parametrize(
    "expected_idx, strdate",
    [(0, "2000-01-01"), (0, "2000-01-29"), (2, "2000-03-29"), (-12, "1999-01-01")],
)
@pytest.mark.parametrize("calendar", all_cftime_calendars)
def test_find_date_idx(expected_idx, strdate, calendar):
    time = xr.cftime_range("2000-01-01", periods=10, freq="1MS")
    date = _construct_cfdate([0], f"days since {strdate}", calendar)
    assert find_date_idx(time, date) == expected_idx


@pytest.mark.parametrize("source_calendar", all_cftime_calendars)
@pytest.mark.parametrize("target_calendar", all_cftime_calendars)
def test_unify_time_simple(source_calendar, target_calendar):
    nt = 24
    # simplest case (same length, just different time convention)
    time_child = xr.DataArray(
        xr.cftime_range("2000-01-01", periods=nt, freq="1MS", calendar=source_calendar),
        dims=["time"],
    )
    time_parent = xr.DataArray(
        xr.cftime_range("1900-01-01", periods=nt, freq="1MS", calendar=target_calendar),
        dims=["time"],
    )

    ds_child = xr.DataArray(
        np.random.rand(12, nt),
        dims=["x", "time"],
        coords={"time": time_child},
    ).to_dataset(name="test")

    ds_child.attrs = {
        "branch_time_in_parent": 0,
        "branch_time_in_child": 0,
        "parent_time_units": "days since 1900-01-01",
    }
    # this should be written when files are actually read from a file, but this is
    # a bit dangerous. Why is the child time units not set?
    ds_child.time.encoding["units"] = "days since 2000-01-01"

    ds_parent = xr.DataArray(
        np.random.rand(12, nt), dims=["x", "time"], coords={"time": time_parent}
    ).to_dataset(name="test")

    ds_parent_adjusted, ds_child_adjusted = unify_time(ds_parent, ds_child)

    xr.testing.assert_allclose(ds_parent_adjusted.time, time_child)

    ds_parent_adjusted, ds_child_adjusted = unify_time(
        ds_parent, ds_child, adjust_to="parent"
    )
    xr.testing.assert_allclose(ds_child_adjusted.time, time_parent)


@pytest.mark.parametrize("source_calendar", all_cftime_calendars)
@pytest.mark.parametrize("target_calendar", all_cftime_calendars)
def test_unify_time_complex(source_calendar, target_calendar):
    nt = 24
    nt_parent = 200
    # more complex and common case (longer control, with starting from 0 convention)
    time_child = xr.DataArray(
        xr.cftime_range("2000-01-01", periods=nt, freq="1MS", calendar=source_calendar),
        dims=["time"],
    )
    time_parent = xr.DataArray(
        xr.cftime_range(
            "0100-01-01", periods=nt_parent, freq="1MS", calendar=target_calendar
        ),
        dims=["time"],
    )

    ds_child = xr.DataArray(
        np.random.rand(12, nt),
        dims=["x", "time"],
        coords={"time": time_child},
    ).to_dataset(name="test")

    ds_child.attrs = {
        "branch_time_in_parent": 0,
        "branch_time_in_child": 0,
        "parent_time_units": "days since 0200-01-01",
    }
    # this should be written when files are actually read from a file, but this is
    # a bit dangerous. Why is the child time units not set?
    ds_child.time.encoding["units"] = "days since 2000-01-01"

    ds_parent = xr.DataArray(
        np.random.rand(12, nt_parent), dims=["x", "time"], coords={"time": time_parent}
    ).to_dataset(name="test")

    ds_parent_adjusted, ds_child_adjusted = unify_time(ds_parent, ds_child)

    expected_time_parent_adjusted = xr.DataArray(
        xr.cftime_range(
            "1900-01-01", periods=nt_parent, freq="1MS", calendar=source_calendar
        ),
        dims=["time"],
    )

    xr.testing.assert_allclose(ds_parent_adjusted.time, expected_time_parent_adjusted)

    ds_parent_adjusted, ds_child_adjusted = unify_time(
        ds_parent, ds_child, adjust_to="parent"
    )

    expected_time_child_adjusted = xr.DataArray(
        xr.cftime_range("0200-01-01", periods=nt, freq="1MS", calendar=target_calendar),
        dims=["time"],
    )
    xr.testing.assert_allclose(ds_child_adjusted.time, expected_time_child_adjusted)


def test_unify_time_missing_attr_warning():
    nt = 24
    # simplest case (same length, just different time convention)
    time_child = xr.cftime_range("2000-01-01", periods=nt, freq="1MS")
    time_parent = xr.cftime_range("1200-01-01", periods=nt, freq="1MS")

    ds_child = xr.DataArray(
        np.random.rand(12, nt), dims=["x", "time"], coords={"time": time_child}
    )
    ds_parent = xr.DataArray(
        np.random.rand(12, nt), dims=["x", "time"], coords={"time": time_parent}
    )
    with pytest.warns(UserWarning):
        ds_parent_adjusted, ds_child_adjusted = unify_time(ds_parent, ds_child)
    xr.testing.assert_equal(ds_parent, ds_parent_adjusted)
    xr.testing.assert_equal(ds_child, ds_child_adjusted)


def test_unify_time_adjust_to_error():
    nt = 24
    # simplest case (same length, just different time convention)
    time_child = xr.DataArray(
        xr.cftime_range("2000-01-01", periods=nt, freq="1MS"),
        dims=["time"],
    )
    time_parent = xr.DataArray(
        xr.cftime_range("1900-01-01", periods=nt, freq="1MS"),
        dims=["time"],
    )

    ds_child = xr.DataArray(
        np.random.rand(12, nt),
        dims=["x", "time"],
        coords={"time": time_child},
    ).to_dataset(name="test")

    ds_child.attrs = {
        "branch_time_in_parent": 0,
        "branch_time_in_child": 0,
        "parent_time_units": "days since 1900-01-01",
    }
    # this should be written when files are actually read from a file, but this is
    # a bit dangerous. Why is the child time units not set?
    ds_child.time.encoding["units"] = "days since 2000-01-01"

    ds_parent = xr.DataArray(
        np.random.rand(12, nt), dims=["x", "time"], coords={"time": time_parent}
    ).to_dataset(name="test")
    with pytest.raises(ValueError):
        ds_parent_adjusted, ds_child_adjusted = unify_time(
            ds_parent, ds_child, adjust_to="nonsense"
        )


@pytest.mark.parametrize("chunk", [False, {"time": 2}])
def test_remove_trend(chunk):

    # normal testing
    time = xr.cftime_range("1850-01-01", periods=5, freq="1AS")
    data = xr.DataArray(
        np.random.rand(3, 4, len(time)),
        dims=["x", "y", "time"],
        coords={"time": time},
        attrs={"just_some": "test"},
    )
    if chunk:
        data = data.chunk(chunk)
    slope = xr.DataArray(np.random.rand(3, 4), dims=["x", "y"])

    ref_date = str(time[0])
    dummy_time = xr.DataArray(np.arange(len(time)), dims=["time"])

    sloped_data = data + (slope * dummy_time)
    sloped_data.attrs = data.attrs

    detrended = remove_trend(sloped_data, slope, ref_date)
    xr.testing.assert_allclose(data, detrended)
    assert detrended.attrs == data.attrs

    # test mask check
    time = xr.cftime_range("1850-01-01", periods=5, freq="1AS")
    data = xr.DataArray(
        np.random.rand(3, 4, len(time)), dims=["x", "y", "time"], coords={"time": time}
    )

    slope = xr.DataArray(
        np.random.rand(3, 4), dims=["x", "y"], attrs={"reference_year": str(time[0])}
    )

    slope[0, 0] = np.nan
    with pytest.raises(ValueError):
        remove_trend(data, slope, ref_date)


def test_calculate_drift_missing_attrs():
    # error if no attr are given
    ds_control = xr.DataArray([0]).to_dataset(name="test")
    ds = xr.DataArray([0]).to_dataset(name="test")
    with pytest.raises(ValueError) as einfo:
        calculate_drift(ds_control, ds, trend_years=250)
    assert "in attributes of `ds`." in str(einfo.value)

    # error for attrs mismatch
    ds.attrs = {
        "source_id": "a",
        "variant_label": "b",
        "branch_time_in_parent": 0,
        "parent_time_units": "something",
        "parent_variant_label": "a",
        "parent_source_id": "a",
    }

    ds_control.attrs = {
        "source_id": "a",
        "variant_label": "b",
    }

    with pytest.raises(ValueError) as einfo:
        calculate_drift(ds_control, ds, "test", trend_years=250)
    assert (
        str(einfo.value)
        == "`ds_parent` variant_label (b) not compatible with `ds` parent_variant_label (a)"
    )


@pytest.mark.parametrize("trend_years", [1, 5, 10])
def test_calculate_drift(trend_years):
    # error if no attr are given
    nx, ny = (10, 20)
    nt_control = 3000
    nt = 24
    time_control = xr.cftime_range("0100-01-01", periods=nt_control, freq="1MS")
    time_ds = xr.cftime_range("2000-01-01", periods=nt, freq="1MS")

    ds_control = xr.DataArray(
        np.random.rand(nx, ny, nt_control),
        dims=["x", "y", "time"],
        coords={"time": time_control},
    ).to_dataset(name="test")

    ds = xr.DataArray(
        np.random.rand(nx, ny, nt),
        dims=["x", "y", "time"],
        coords={"time": time_ds},
    ).to_dataset(name="test")

    ds.attrs = {
        "source_id": "a",
        "variant_label": "a",
        "branch_time_in_parent": 0,
        "parent_time_units": "days since 0105-01-01",
        "parent_variant_label": "a",
        "parent_source_id": "a",
    }

    ds_control.attrs = {
        "source_id": "a",
        "variant_label": "a",
    }

    print(ds_control)
    print(ds)

    reg_expected = (
        ds_control.isel(time=slice(5 * 12, 5 * 12 + trend_years * 12))
        .test.polyfit("time", 1)
        .sel(degree=1)
        .polyfit_coefficients.reset_coords(drop=True)
    )
    reg = calculate_drift(ds_control, ds, "test", trend_years=trend_years)

    xr.testing.assert_allclose(reg_expected, reg.test)
    assert reg.attrs == ds.attrs
