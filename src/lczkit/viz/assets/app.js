/*
 * lczkit map site — interaction only.
 *
 * Everything this file draws was decided by the run and written into `style.json` and
 * `manifest.json`: the LCZ colours, the choropleth class boundaries, the parameter units, the
 * legend text. Nothing here computes a quantile, a break or a parameter, which is the constraint
 * the whole Phase 7 design is built around.
 *
 * Switching a layer calls `setPaintProperty` on one already-loaded fill layer. It never swaps a
 * source, never calls `setStyle`, and therefore never refetches a tile — the tiles for the current
 * viewport are already in memory and carry every attribute a view can paint.
 */

(function () {
  "use strict";

  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);

  const state = {
    views: [],
    viewById: new Map(),
    activeView: null,
    selected: null,
    meta: null,
    base: "run",
  };

  function el(id) {
    return document.getElementById(id);
  }

  /* ---------------------------------------------------------------- permalink */

  /*
   * The hash is the citation mechanism: a specific unit in a specific view at a specific zoom has
   * a URL, so a paper can point at one cell rather than at "the map". Order is fixed and
   * positional so an old link keeps working if a field is ever appended.
   */
  function readHash() {
    const raw = window.location.hash.replace(/^#/, "");
    if (!raw) return null;
    const [view, zoom, lat, lon, unit] = raw.split("/");
    const parsed = { view, zoom: Number(zoom), lat: Number(lat), lon: Number(lon), unit: unit || null };
    if (!Number.isFinite(parsed.zoom) || !Number.isFinite(parsed.lat) || !Number.isFinite(parsed.lon)) {
      return null;
    }
    return parsed;
  }

  function writeHash(map) {
    const centre = map.getCenter();
    const parts = [
      state.activeView ? state.activeView.id : "lcz",
      map.getZoom().toFixed(2),
      centre.lat.toFixed(5),
      centre.lng.toFixed(5),
      state.selected == null ? "" : encodeURIComponent(state.selected),
    ];
    const hash = "#" + parts.join("/");
    if (hash !== window.location.hash) {
      window.history.replaceState(null, "", hash);
    }
  }

  /* ------------------------------------------------------------------- legend */

  function renderLegend(container, entries, unit) {
    container.replaceChildren();
    entries.forEach(function (entry) {
      const row = document.createElement("div");
      row.className = entry.nodata ? "legend-row nodata" : "legend-row";
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.backgroundColor = entry.colour;
      const label = document.createElement("span");
      /*
       * The unit goes on the first band only. Repeating it down every row of a seven-band ramp is
       * noise, and omitting it entirely leaves a column of bare numbers whose meaning is a scroll
       * away in the description.
       */
      const first = container.childElementCount === 0;
      label.textContent = unit && first && !entry.nodata ? entry.label + " " + unit : entry.label;
      row.append(swatch, label);
      container.append(row);
    });
  }

  /* -------------------------------------------------------------------- views */

  function applyView(map, view) {
    state.activeView = view;
    map.setPaintProperty(state.meta.fill_layer, "fill-color", view.paint);
    el("view-description").textContent = view.unit
      ? view.description + " (" + view.unit + ")"
      : view.description;
    renderLegend(el("legend"), view.legend, view.unit);
    el("hover-readout").textContent = "";
    writeHash(map);
  }

  /* --------------------------------------------------------------------- base */

  /*
   * The ground under the units. `run` is the layers the run itself persisted — its cleaned water
   * and streets — and is the default precisely because it needs no network: an archived site opened
   * years from now still draws it. `raster` exists only when the run was built with an online
   * basemap, and is treated as fallible rather than assumed.
   */
  function setBase(map, choice) {
    const base = state.meta.basemap || {};
    const runLayers = base.run_layers || [];
    state.base = choice;

    runLayers.forEach(function (id) {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, "visibility", choice === "run" ? "visible" : "none");
      }
    });
    if (base.raster_layer && map.getLayer(base.raster_layer)) {
      map.setLayoutProperty(
        base.raster_layer,
        "visibility",
        choice === "raster" ? "visible" : "none"
      );
    }
    /*
     * The LCZ palette was built for a light figure on a dark ground. Over a light raster the same
     * fill at the same opacity washes out, so the floor rises with the basemap rather than leaving
     * the reader to discover the problem and fix it with the slider.
     */
    if (choice === "raster" && base.raster_dark === false) {
      const slider = el("opacity");
      if (Number(slider.value) < 70) {
        slider.value = "70";
        setOpacity(map, 70);
      }
    }
    Array.prototype.forEach.call(document.querySelectorAll("[name=base]"), function (input) {
      input.checked = input.value === choice;
    });
  }

  function setOpacity(map, percent) {
    map.setPaintProperty(state.meta.fill_layer, "fill-opacity", percent / 100);
    el("opacity-value").textContent = percent + "%";
  }

  function buildBaseOptions(map) {
    const base = state.meta.basemap || {};
    const container = el("base-options");
    const choices = [{ value: "none", label: "None" }, { value: "run", label: "Run's own linework" }];
    if (base.raster_layer) choices.push({ value: "raster", label: base.raster_label });

    container.replaceChildren();
    choices.forEach(function (choice) {
      const row = document.createElement("label");
      row.className = "checkbox";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "base";
      input.value = choice.value;
      input.checked = choice.value === "run";
      input.addEventListener("change", function () {
        setBase(map, choice.value);
      });
      row.append(input, document.createTextNode(" " + choice.label));
      container.append(row);
    });

    if (base.raster_layer) {
      const note = el("base-note");
      note.hidden = false;
      note.textContent =
        base.raster_label + " tiles are fetched from the network (" + base.raster_licence + ").";
    }
  }

  /* --------------------------------------------------------------- unit panel */

  function definitionList(node, rows) {
    node.replaceChildren();
    rows.forEach(function (row) {
      const term = document.createElement("dt");
      term.textContent = row.label;
      const value = document.createElement("dd");
      value.textContent = row.value;
      node.append(term, value);
    });
  }

  function formatValue(value, unit) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "number") {
      const text = Math.abs(value) >= 1000 ? value.toFixed(0) : String(Number(value.toPrecision(3)));
      return unit ? text + " " + unit : text;
    }
    return String(value);
  }

  /*
   * The distance vector is stored as scaled integers — the run divided by `viz_distance_scale` to
   * fit int16 — so it is rescaled here rather than re-derived. The bars are drawn as plain divs:
   * a charting library would be a second vendored bundle for seventeen rectangles.
   */
  function renderDistances(container, properties) {
    container.replaceChildren();
    const scale = state.meta.distance_scale || 1000;
    const entries = state.meta.distance_columns
      .map(function (column, index) {
        const raw = properties[column];
        return {
          label: state.meta.distance_labels[index],
          value: raw === undefined || raw === null ? null : raw / scale,
        };
      })
      .filter(function (entry) {
        return entry.value !== null;
      });
    if (!entries.length) {
      container.textContent = "not carried in these tiles";
      return;
    }
    const largest = Math.max.apply(
      null,
      entries.map(function (entry) {
        return entry.value;
      })
    );
    entries.forEach(function (entry) {
      const row = document.createElement("div");
      row.className = "bar-row";
      const label = document.createElement("span");
      label.className = "bar-label";
      label.textContent = entry.label;
      const track = document.createElement("span");
      track.className = "bar-track";
      const fill = document.createElement("span");
      fill.className = "bar-fill";
      fill.style.width = largest > 0 ? (100 * entry.value) / largest + "%" : "0%";
      const value = document.createElement("span");
      value.className = "bar-value";
      value.textContent = entry.value.toFixed(2);
      track.append(fill);
      row.append(label, track, value);
      container.append(row);
    });
  }

  /* The display name the run recorded for a column, falling back the way the style module does. */
  function labelFor(column) {
    const labels = state.meta.labels || {};
    if (labels[column]) return labels[column];
    const prefix = "height_frac_";
    if (column.indexOf(prefix) === 0) {
      const source = column.slice(prefix.length);
      const sources = state.meta.height_source_labels || {};
      return sources[source] || source.replace(/_/g, " ");
    }
    return column.replace(/_/g, " ");
  }

  function showUnit(properties) {
    el("unit-empty").hidden = true;
    el("unit-detail").hidden = false;
    el("unit-id").textContent = properties.unit_id || "";

    const primary = properties.lcz_primary;
    const secondary = properties.lcz_secondary;
    definitionList(el("unit-summary"), [
      { label: "Class", value: state.meta.class_names[primary] || "—" },
      { label: "Second nearest", value: state.meta.class_names[secondary] || "—" },
      { label: "Uniqueness", value: formatValue(properties.uniqueness, "") },
      { label: "Parameters used", value: formatValue(properties.n_params_used, "") },
      { label: "Label route", value: routeLabel(properties.label_route) },
    ]);

    /*
     * A built cell has at most three metric dimensions and a natural one at most seven, so a low
     * count is not a rounding detail — it is most of the evidence missing. `aspect_ratio` alone is
     * null wherever no street reaches a building.
     */
    const used = Number(properties.n_params_used);
    const badge = el("unit-confidence");
    if (Number.isFinite(used) && used <= 2) {
      badge.hidden = false;
      badge.textContent = "Low confidence — only " + used + " parameter" + (used === 1 ? "" : "s");
    } else {
      badge.hidden = true;
    }

    renderDistances(el("distance-chart"), properties);

    /*
     * Which tier-fraction columns exist depends on which height sources fired for this run, so the
     * height block is discovered from the feature rather than enumerated: a run with no areal tier
     * simply shows fewer rows instead of five empty ones.
     */
    const heightRows = Object.keys(properties)
      .filter(function (key) {
        return state.meta.height_prefixes.some(function (prefix) {
          return key.indexOf(prefix) === 0;
        });
      })
      .sort()
      .map(function (column) {
        return { label: labelFor(column), value: formatValue(properties[column], "") };
      });
    definitionList(el("unit-heights"), heightRows);

    definitionList(
      el("unit-parameters"),
      state.meta.parameters
        .filter(function (parameter) {
          return properties[parameter.name] !== undefined;
        })
        .map(function (parameter) {
          return {
            label: parameter.label || labelFor(parameter.name),
            value: formatValue(properties[parameter.name], parameter.unit),
          };
        })
    );
  }

  /*
   * `label_route` records whether a cell took the distance metric or the functional LCZ 10 rule.
   * Printed raw it is a token; the point of showing it at all is that those are different claims.
   */
  function routeLabel(route) {
    /* These keys are `lczkit.classify.rules.ROUTES`, and a test asserts the two agree. */
    const routes = {
      distance_built: "nearest built prototype",
      distance_natural: "nearest natural prototype",
      industrial_rule: "industrial rule (LCZ 10)",
    };
    if (route === null || route === undefined || route === "") return "—";
    return routes[route] || String(route);
  }

  /*
   * Detail attributes live in a second tileset built at the maximum zoom only, because carrying
   * them at every zoom costs more than the entire building layer. `querySourceFeatures` reads what
   * is already loaded; it issues no request of its own.
   */
  function detailProperties(map, unitId) {
    if (!state.meta.detail_source) return null;
    const features = map.querySourceFeatures(state.meta.detail_source, {
      sourceLayer: "units_detail",
      filter: ["==", ["get", "unit_id"], unitId],
    });
    return features.length ? features[0].properties : null;
  }

  /*
   * The source promotes `unit_id` to the MapLibre feature id, so the selection highlight is a
   * feature-state keyed on the same identifier every other stage of the pipeline uses. Highlighting
   * through feature-state rather than through a filter matters: a filter change invalidates the
   * layer and re-reads the source, and clicking a unit must not refetch a tile.
   */
  function unitState(unitId) {
    return {
      source: state.meta.units_source,
      sourceLayer: state.meta.units_source_layer,
      id: unitId,
    };
  }

  function select(map, feature) {
    if (state.selected != null) {
      map.setFeatureState(unitState(state.selected), { selected: false });
    }
    state.selected = feature.id != null ? feature.id : feature.properties.unit_id;
    map.setFeatureState(unitState(state.selected), { selected: true });
    const detail = detailProperties(map, state.selected);
    showUnit(Object.assign({}, feature.properties, detail || {}));
    writeHash(map);
  }

  /* -------------------------------------------------------------------- about */

  /*
   * What this run was, read out of the manifest it already carries. It answers the questions a
   * reader has to answer before trusting any of the rest — which cascade filled the heights, which
   * weights the metric used, how much of the map rests on measured heights — without asking them to
   * open a JSON file.
   */
  function renderAbout(manifest, meta) {
    const config = manifest.config || {};
    const rows = [{ label: "Run", value: meta.run_id || "—" }];

    const units = config.viz ? "grid, 100 m" : null;
    if (units) rows.push({ label: "Units", value: units });

    const heights = config.heights || {};
    const tiers = (heights.areal_tiers || [])
      .filter(function (tier) {
        return tier.enabled;
      })
      .map(function (tier) {
        return tier.name;
      });
    rows.push({
      label: "Height cascade",
      value: tiers.length ? "Overture, then " + tiers.join(", ") : "Overture only",
    });

    if (config.classification && config.classification.weight_preset) {
      rows.push({ label: "Weights", value: config.classification.weight_preset });
    }
    if (config.overture && config.overture.release) {
      rows.push({ label: "Overture release", value: config.overture.release });
    }
    const base = meta.basemap || {};
    rows.push({
      label: "Base map",
      value: base.raster_layer
        ? "run's own linework, plus " + base.raster_label + " (network)"
        : "run's own linework — this site needs no network",
    });
    definitionList(el("about"), rows);
  }

  /* --------------------------------------------------------------------- boot */

  Promise.all([
    fetch("style.json").then(function (r) {
      return r.json();
    }),
    fetch("manifest.json").then(function (r) {
      return r.json();
    }),
  ])
    .then(function (loaded) {
      const style = loaded[0];
      const manifest = loaded[1];
      const meta = style.metadata.lczkit;

      const legend = manifest.legend || {};
      meta.class_names = {};
      Object.keys(legend).forEach(function (code) {
        meta.class_names[Number(code)] = legend[code].label + " — " + legend[code].name;
      });
      meta.distance_scale =
        (manifest.config && manifest.config.output && manifest.config.output.viz_distance_scale) ||
        1000;
      meta.parameters = manifest.parameters || [];
      state.meta = meta;
      state.views = meta.views;
      meta.views.forEach(function (view) {
        state.viewById.set(view.id, view);
      });

      el("run-id").textContent = meta.run_id || "";
      document.title = "lczkit — " + (meta.run_id || "Local Climate Zones");

      const initial = readHash();
      const map = new maplibregl.Map({
        container: "map",
        style: style,
        center: initial ? [initial.lon, initial.lat] : meta.centre,
        zoom: initial ? initial.zoom : 10.5,
        maxZoom: 18,
        pitch: 0,
        /*
         * Off when everything is local — the footer carries the attribution and a control would be
         * a second copy of it. On when a run configured a remote basemap, because every provider
         * requires attribution and MapLibre reads it off the source rather than from this page.
         */
        attributionControl: (meta.basemap && meta.basemap.raster_layer) ? {compact: true} : false,
      });
      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-left");
      map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

      /*
       * Grouped rather than flat. The order inside each group is the one `style.selector_rank`
       * decided and a test asserts; the groups only make that order visible, so that a reader
       * scanning thirteen entries can see that height provenance is a category rather than one
       * more parameter among the choropleths.
       */
      const select_ = el("view");
      const groups = new Map();
      (meta.groups || []).forEach(function (name) {
        groups.set(name, null);
      });
      meta.views.forEach(function (view) {
        const name = view.group || "";
        if (!groups.get(name)) {
          const group = document.createElement("optgroup");
          group.label = name;
          groups.set(name, group);
          select_.append(group);
        }
        const option = document.createElement("option");
        option.value = view.id;
        option.textContent = view.label;
        groups.get(name).append(option);
      });
      const startView = (initial && state.viewById.get(initial.view)) || meta.views[0];
      select_.value = startView.id;

      buildBaseOptions(map);
      renderAbout(manifest, meta);

      map.on("load", function () {
        applyView(map, startView);
        setBase(map, "run");
        setOpacity(map, Number(el("opacity").value));
        if (!meta.buildings_layer) return;
        el("buildings-section").hidden = false;
        renderLegend(el("buildings-legend"), meta.building_colour_by.height_source_legend);
        el("buildings-legend").hidden = true;
      });

      el("opacity").addEventListener("input", function (event) {
        setOpacity(map, Number(event.target.value));
      });

      /*
       * A remote basemap is the one thing here that can fail, and it fails silently — MapLibre
       * reports the tile error and carries on with a blank ground. Saying so keeps a network
       * problem from reading as a broken map, which is the whole reason the offline default exists.
       */
      map.on("error", function (event) {
        const source = event && event.sourceId;
        if (!source || source !== "basemap-raster") return;
        const note = el("base-note");
        note.hidden = false;
        note.className = "error";
        note.textContent =
          "Base map tiles could not be loaded — you may be offline. Everything else on this map " +
          "is served from this directory; switch the base back to the run's own linework.";
      });

      select_.addEventListener("change", function () {
        applyView(map, state.viewById.get(select_.value));
      });

      if (meta.buildings_layer) {
        el("buildings-toggle").addEventListener("change", function (event) {
          map.setLayoutProperty(
            meta.buildings_layer,
            "visibility",
            event.target.checked ? "visible" : "none"
          );
        });
        el("buildings-colour").addEventListener("change", function (event) {
          const mode = event.target.value;
          map.setPaintProperty(
            meta.buildings_layer,
            "fill-extrusion-color",
            meta.building_colour_by[mode]
          );
          el("buildings-legend").hidden = mode !== "height_source";
        });
      }

      map.on("click", meta.fill_layer, function (event) {
        if (event.features && event.features.length) select(map, event.features[0]);
      });
      map.on("mouseenter", meta.fill_layer, function () {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", meta.fill_layer, function () {
        map.getCanvas().style.cursor = "";
        el("hover-readout").textContent = "";
      });

      /*
       * Reading a choropleth off a legend means matching a shade to a band by eye, which is exactly
       * the comparison a sequential ramp is worst at. The value under the cursor removes the guess.
       * It reads the feature already under the pointer, so it costs no request.
       */
      map.on("mousemove", meta.fill_layer, function (event) {
        if (!event.features || !event.features.length || !state.activeView) return;
        const view = state.activeView;
        const raw = event.features[0].properties[view.column];
        const readout = el("hover-readout");
        if (view.kind === "categorical") {
          readout.textContent = state.meta.class_names[Number(raw)] || "no value";
          return;
        }
        readout.textContent =
          view.label + ": " + formatValue(raw === undefined ? null : Number(raw), view.unit);
      });
      map.on("moveend", function () {
        writeHash(map);
      });
    })
    .catch(function (error) {
      const panel = el("panel");
      const message = document.createElement("p");
      message.className = "error";
      message.textContent =
        "Could not load the site: " +
        error +
        ". This page must be served over HTTP — open it with `python serve.py` rather than from the filesystem.";
      panel.prepend(message);
    });
})();
