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

  const state = { views: [], viewById: new Map(), activeView: null, selected: null, meta: null };

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

  function renderLegend(container, entries) {
    container.replaceChildren();
    entries.forEach(function (entry) {
      const row = document.createElement("div");
      row.className = "legend-row";
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.backgroundColor = entry.colour;
      const label = document.createElement("span");
      label.textContent = entry.label;
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
    renderLegend(el("legend"), view.legend);
    writeHash(map);
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

  function showUnit(properties) {
    el("unit-empty").hidden = true;
    el("unit-detail").hidden = false;
    el("unit-id").textContent = properties.unit_id || "";

    const primary = properties.lcz_primary;
    const secondary = properties.lcz_secondary;
    definitionList(el("unit-summary"), [
      { label: "Primary", value: state.meta.class_names[primary] || "—" },
      { label: "Secondary", value: state.meta.class_names[secondary] || "—" },
      { label: "Uniqueness", value: formatValue(properties.uniqueness, "") },
      { label: "Parameters used", value: formatValue(properties.n_params_used, "") },
      { label: "Label route", value: formatValue(properties.label_route, "") },
    ]);

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
        return { label: column.replace(/_/g, " "), value: formatValue(properties[column], "") };
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
            label: parameter.name.replace(/_/g, " "),
            value: formatValue(properties[parameter.name], parameter.unit),
          };
        })
    );
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
        attributionControl: false,
      });
      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-left");
      map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

      const select_ = el("view");
      meta.views.forEach(function (view) {
        const option = document.createElement("option");
        option.value = view.id;
        option.textContent = view.label;
        select_.append(option);
      });
      const startView = (initial && state.viewById.get(initial.view)) || meta.views[0];
      select_.value = startView.id;

      map.on("load", function () {
        applyView(map, startView);
        if (!meta.buildings_layer) return;
        el("buildings-section").hidden = false;
        renderLegend(el("buildings-legend"), meta.building_colour_by.height_source_legend);
        el("buildings-legend").hidden = true;
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
