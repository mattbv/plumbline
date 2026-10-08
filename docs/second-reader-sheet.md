# Second-reader sheet

Thirty of the 67 findings Plumbline reports on six packages it was not developed against (`statsmodels`, `geopandas`, `bokeh`, `pint`, `altair`, `pyproj`), in random order. The maintainer's own reading is deliberately not shown.

For each, mark one:

- **real**: the docs and the code genuinely disagree, and a reader could be misled;
- **by-design**: they disagree only in a way the project has chosen to report (for example the docs omit a `None` the code allows, PRD §14 #10), and you think reporting it is reasonable;
- **noise**: you would not want to see this finding;
- **misread**: Plumbline misread the code or the docs.

Versions read (wheels, unpacked and read statically, never run): `statsmodels` 0.15.0, `geopandas` 1.2.0, `bokeh` 3.10.0, `pint` 0.26.1, `altair` 6.3.0, `pyproj` 3.8.0. Each package is ingested as a single commit.

## 1. `altair` · `TopLevelMixin.transform_quantile` · `param.step.type`

- Code says: `None | float`
- Docs say: `float`
- Signature: `transform_quantile(self, quantile: str | FieldName, as_: Optional[list[str | FieldName]]=Undefined, groupby: Optional[list[str | FieldName]]=Undefined, probs: Optional[list[float]]=Undefined, step: Optional[float]=Undefined) -> Self`
- Docstring line: `step : float
            A probability step size (default 0.01) for sampling quantile values. All values from`
- Your reading: real / by-design / noise / misread

## 2. `altair` · `JupyterChart.__init__` · `param.embed_options.type`

- Code says: `None | dict`
- Docs say: `dict`
- Signature: `__init__(self, chart: TopLevelSpec, debounce_wait: int=10, max_wait: bool=True, debug: bool=False, embed_options: dict | None=None, **kwargs: Any)`
- Docstring line: `embed_options: dict
             Options to pass to vega-embed.`
- Your reading: real / by-design / noise / misread

## 3. `pint` · `find_connected_nodes` · `returns.type`

- Code says: `None | set[TH]`
- Docs say: `set[TH]`
- Signature: `find_connected_nodes(graph: dict[TH, set[TH]], start: TH, visited: set[TH] | None=None) -> set[TH] | None`
- Docstring line: (not found by a simple search)
- Your reading: real / by-design / noise / misread

## 4. `bokeh` · `ModelEvent.__init__` · `param.model.type`

- Code says: `Model | None`
- Docs say: `Model`
- Signature: `__init__(self, model: Model | None) -> None`
- Docstring line: `model (Model) : a Bokeh model to register event callbacks on`
- Your reading: real / by-design / noise / misread

## 5. `geopandas` · `GeoDataFrame.to_crs` · `returns.type`

- Code says: `GeoDataFrame | None`
- Docs say: `GeoDataFrame`
- Signature: `to_crs(self, crs: Any | None=None, epsg: int | None=None, inplace: bool=False) -> GeoDataFrame | None`
- Docstring line: (not found by a simple search)
- Your reading: real / by-design / noise / misread

## 6. `pint` · `GenericPlainRegistry.parse_pattern` · `param.pattern_string.exists`

- Code says: `false`
- Docs say: `true`
- Signature: `parse_pattern(self, input_string: str, pattern: str, case_sensitive: bool | None=None, many: bool=False) -> list[str] | str | None`
- Docstring line: `pattern_string:
            The regex parse string
        case_sensitive, optional`
- Your reading: real / by-design / noise / misread

## 7. `bokeh` · `Plot.add_glyph` · `param.glyph.type`

- Code says: `Glyph | None`
- Docs say: `Glyph`
- Signature: `add_glyph(self, source_or_glyph: Glyph | ColumnarDataSource, glyph: Glyph | None=None, **kwargs: Any) -> GlyphRenderer`
- Docstring line: `glyph (Glyph) : the glyph to add to the Plot


        Keyword Arguments:`
- Your reading: real / by-design / noise / misread

## 8. `bokeh` · `export_svgs` · `param.height.type`

- Code says: `None | int`
- Docs say: `int`
- Signature: `export_svgs(obj: UIElement | Document, *, filename: str | None=None, width: int | None=None, height: int | None=None, webdriver: DriverLike | None=None, timeout: int=5, state: State | None=None, backend: ExportBackendType | None=None) -> list[str]`
- Docstring line: `height (int) : the desired height of the exported layout obj only if
            it's a Plot instance. Otherwise the height kwarg is ignored.`
- Your reading: real / by-design / noise / misread

## 9. `pyproj` · `HotineObliqueMercatorBConversion.__new__` · `param.azimuth_projection_centre.type`

- Code says: `None | float`
- Docs say: `float`
- Signature: `__new__(cls, latitude_projection_centre: float, longitude_projection_centre: float, angle_from_rectified_to_skew_grid: float, easting_projection_centre: float=0.0, northing_projection_centre: float=0.0, azimuth_projection_centre: Optional[float]=None, scale_fa`
- Docstring line: `azimuth_projection_centre: float
            Azimuth of initial line (alpha).`
- Your reading: real / by-design / noise / misread

## 10. `statsmodels` · `OLSResults.el_test` · `param.return_weights.default`

- Code says: `0`
- Docs say: `False`
- Signature: `el_test(self, b0_vals, param_nums, return_weights=0, ret_params=0, method='nm', stochastic_exog=1, *, result_object: bool | None=None)`
- Docstring line: `return_weights : bool, optional
            If true, returns the weights that optimize the likelihood`
- Your reading: real / by-design / noise / misread

## 11. `bokeh` · `check_token_signature` · `param.secret_key.type`

- Code says: `None | bytes`
- Docs say: `None | str`
- Signature: `check_token_signature(token: str, secret_key: bytes | None=settings.secret_key_bytes(), signed: bool=settings.sign_sessions()) -> bool`
- Docstring line: `secret_key (str, optional) :
            Secret key (default: value of BOKEH_SECRET_KEY environment variable)

        signed (bool, optional) :`
- Your reading: real / by-design / noise / misread

## 12. `pyproj` · `Transformer.transform_bounds` · `param.densify_points.exists`

- Code says: `false`
- Docs say: `true`
- Signature: `transform_bounds(self, left: float, bottom: float, right: float, top: float, densify_pts: int=21, radians: bool=False, errcheck: bool=False, direction: TransformDirection | str=TransformDirection.FORWARD) -> tuple[float, float, float, float]`
- Docstring line: `densify_points: uint, default=21
            Number of points to add to each edge to account for nonlinear edges`
- Your reading: real / by-design / noise / misread

## 13. `statsmodels` · `OLSResults.el_test` · `param.ret_params.default`

- Code says: `0`
- Docs say: `False`
- Signature: `el_test(self, b0_vals, param_nums, return_weights=0, ret_params=0, method='nm', stochastic_exog=1, *, result_object: bool | None=None)`
- Docstring line: `ret_params : bool, optional
            If true, returns the parameter vector that maximizes the likelihood`
- Your reading: real / by-design / noise / misread

## 14. `bokeh` · `RGB.from_css` · `param.css_color.exists`

- Code says: `false`
- Docs say: `true`
- Signature: `from_css(cls, css_color_string: str) -> RGB`
- Docstring line: `css_color (str) :
                String containing RGBA values. Valid formats are "rgb(125, 123, 12)" or
                "rgba(125, 123, 12, 0.1)". The RGB values can be in the range between 0 and 25`
- Your reading: real / by-design / noise / misread

## 15. `pyproj` · `Transformer.from_proj` · `deprecated`

- Code says: `false`
- Docs say: `true`
- Signature: `from_proj(proj_from: Any, proj_to: Any, always_xy: bool=False, area_of_interest: AreaOfInterest | None=None) -> 'Transformer'`
- Docstring line: `.. deprecated:: 3.4.1 :meth:`~Transformer.from_crs` is preferred.`
- Your reading: real / by-design / noise / misread

## 16. `pyproj` · `HotineObliqueMercatorBConversion.__new__` · `param.azimuth_initial_line.type`

- Code says: `None | float`
- Docs say: `float`
- Signature: `__new__(cls, latitude_projection_centre: float, longitude_projection_centre: float, angle_from_rectified_to_skew_grid: float, easting_projection_centre: float=0.0, northing_projection_centre: float=0.0, azimuth_projection_centre: Optional[float]=None, scale_fa`
- Docstring line: `azimuth_initial_line: float
            Deprecated alias for azimuth_projection_centre,`
- Your reading: real / by-design / noise / misread

## 17. `bokeh` · `WSHandler.on_message` · `param.fragment.exists`

- Code says: `false`
- Docs say: `true`
- Signature: `on_message(self, message: str | bytes) -> None`
- Docstring line: `fragment (unicode or bytes) : wire fragment to process`
- Your reading: real / by-design / noise / misread

## 18. `geopandas` · `assert_geoseries_equal` · `param.check_dtype.default`

- Code says: `True`
- Docs say: `False`
- Signature: `assert_geoseries_equal(left, right, check_dtype=True, check_index_type=False, check_series_type=True, check_less_precise=False, check_geom_type=False, check_crs=True, normalize=False)`
- Docstring line: `check_dtype : bool, default False
        If True, check geo dtype [only included so it's a drop-in replacement`
- Your reading: real / by-design / noise / misread

## 19. `altair` · `TopLevelMixin.repeat` · `param.row.type`

- Code says: `None | list[str]`
- Docs say: `list`
- Signature: `repeat(self, repeat: Optional[list[str]]=Undefined, row: Optional[list[str]]=Undefined, column: Optional[list[str]]=Undefined, layer: Optional[list[str]]=Undefined, columns: Optional[int]=Undefined, **kwargs: Any) -> RepeatChart`
- Docstring line: `row : list
            a list of data column names to be mapped to the row facet`
- Your reading: real / by-design / noise / misread

## 20. `pyproj` · `PolarStereographicAConversion.__new__` · `param.scale_factor_natural_origin.default`

- Code says: `1`
- Docs say: `0`
- Signature: `__new__(cls, latitude_natural_origin: float, longitude_natural_origin: float=0.0, false_easting: float=0.0, false_northing: float=0.0, scale_factor_natural_origin: float=1.0)`
- Docstring line: `scale_factor_natural_origin: float, default=0.0
            Scale factor at natural origin (k or k_0).`
- Your reading: real / by-design / noise / misread

## 21. `pint` · `GenericPlainRegistry.parse_pattern` · `param.optional.exists`

- Code says: `false`
- Docs say: `true`
- Signature: `parse_pattern(self, input_string: str, pattern: str, case_sensitive: bool | None=None, many: bool=False) -> list[str] | str | None`
- Docstring line: (not found by a simple search)
- Your reading: real / by-design / noise / misread

## 22. `bokeh` · `export_svg` · `param.height.type`

- Code says: `None | int`
- Docs say: `int`
- Signature: `export_svg(obj: UIElement | Document, *, filename: PathLike | None=None, width: int | None=None, height: int | None=None, webdriver: DriverLike | None=None, timeout: int=5, state: State | None=None, backend: ExportBackendType | None=None) -> list[str]`
- Docstring line: `height (int) : the desired height of the exported layout obj only if
            it's a Plot instance. Otherwise the height kwarg is ignored.`
- Your reading: real / by-design / noise / misread

## 23. `statsmodels` · `OriginResults.el_test` · `param.return_weights.default`

- Code says: `0`
- Docs say: `False`
- Signature: `el_test(self, b0_vals, param_nums, method='nm', stochastic_exog=1, return_weights=0, *, result_object=None)`
- Docstring line: `return_weights : bool, optional
            If true, returns the weights that optimize the likelihood`
- Your reading: real / by-design / noise / misread

## 24. `statsmodels` · `OriginResults.el_test` · `param.stochastic_exog.default`

- Code says: `1`
- Docs say: `True`
- Signature: `el_test(self, b0_vals, param_nums, method='nm', stochastic_exog=1, return_weights=0, *, result_object=None)`
- Docstring line: `stochastic_exog : bool, optional
            When True, the exogenous variables are assumed to be stochastic.`
- Your reading: real / by-design / noise / misread

## 25. `altair` · `TopLevelMixin.transform_loess` · `param.bandwidth.type`

- Code says: `None | float`
- Docs say: `float`
- Signature: `transform_loess(self, on: str | FieldName, loess: str | FieldName, as_: Optional[list[str | FieldName]]=Undefined, bandwidth: Optional[float]=Undefined, groupby: Optional[list[str | FieldName]]=Undefined) -> Self`
- Docstring line: `bandwidth : float
            A bandwidth parameter in the range ``[0, 1]`` that determines the amount of`
- Your reading: real / by-design / noise / misread

## 26. `statsmodels` · `GMM.gradient_momcond` · `param.TODO.exists`

- Code says: `false`
- Docs say: `true`
- Signature: `gradient_momcond(self, params, epsilon=0.0001, centered=True)`
- Docstring line: `TODO: looks like not used yet
              missing argument `weights``
- Your reading: real / by-design / noise / misread

## 27. `altair` · `TopLevelMixin.repeat` · `param.layer.type`

- Code says: `None | list[str]`
- Docs say: `list`
- Signature: `repeat(self, repeat: Optional[list[str]]=Undefined, row: Optional[list[str]]=Undefined, column: Optional[list[str]]=Undefined, layer: Optional[list[str]]=Undefined, columns: Optional[int]=Undefined, **kwargs: Any) -> RepeatChart`
- Docstring line: `layer : list
            a list of data column names to be layered. This cannot be`
- Your reading: real / by-design / noise / misread

## 28. `statsmodels` · `OLSResults.el_test` · `param.stochastic_exog.default`

- Code says: `1`
- Docs say: `True`
- Signature: `el_test(self, b0_vals, param_nums, return_weights=0, ret_params=0, method='nm', stochastic_exog=1, *, result_object: bool | None=None)`
- Docstring line: `stochastic_exog : bool, optional
            When True, the exogenous variables are assumed to be stochastic.`
- Your reading: real / by-design / noise / misread

## 29. `altair` · `TopLevelMixin.transform_density` · `param.minsteps.type`

- Code says: `None | int`
- Docs say: `int`
- Signature: `transform_density(self, density: str | FieldName, as_: Optional[list[str | FieldName]]=Undefined, bandwidth: Optional[float]=Undefined, counts: Optional[bool]=Undefined, cumulative: Optional[bool]=Undefined, extent: Optional[list[float]]=Undefined, groupby: Op`
- Docstring line: `minsteps : int
            The minimum number of samples to take along the extent domain for plotting the`
- Your reading: real / by-design / noise / misread

## 30. `bokeh` · `init` · `param.bokehjs_version.type`

- Code says: `None | str`
- Docs say: `str`
- Signature: `init(base_dir: PathLike, *, interactive: bool=False, verbose: bool=False, bokehjs_version: str | None=None, debug: bool=False) -> bool`
- Docstring line: `bokehjs_version (str) : Use a specific version of bokehjs.

        debug (bool) : Allow for remote debugging.`
- Your reading: real / by-design / noise / misread

