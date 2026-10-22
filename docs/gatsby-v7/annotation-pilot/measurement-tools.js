/* Pure measurement functions shared by the local-only guide and regression tests. */
(function (root) {
  function rgb(value) {
    if (!Array.isArray(value) || value.length !== 3 || value.some(v => !Number.isFinite(v) || v < 0 || v > 255)) throw Error('Use three RGB values from 0 to 255.');
    return value;
  }
  function neutralRange(sample) {
    rgb(sample);
    const start = [217, 221, 222], end = [242, 238, 231], tolerance = 5;
    let low = 0, high = 1;
    for (let c = 0; c < 3; c++) {
      const delta = end[c] - start[c];
      low = Math.max(low, (sample[c] - tolerance - start[c]) / delta);
      high = Math.min(high, (sample[c] + tolerance - start[c]) / delta);
    }
    return low <= high;
  }
  function matches(sample, colours, tolerance) {
    return colours.some(colour => sample.every((v, i) => Math.abs(v - colour[i]) <= tolerance));
  }
  function area(image, mask, colours, tolerance, limit) {
    if (!image.length || image.length !== mask.length || image.length % 4) throw Error('Image and mask must have the same nonzero dimensions.');
    if (!colours.length) throw Error('Enter at least one colour.');
    colours.forEach(rgb);
    if (!Number.isFinite(tolerance) || tolerance < 0 || tolerance > 255 || !Number.isFinite(limit) || limit < 0 || limit > 100) throw Error('Invalid tolerance or percentage.');
    let selected = 0, matching = 0;
    for (let i = 0; i < image.length; i += 4) {
      const pixel = [mask[i], mask[i + 1], mask[i + 2]];
      const white = pixel.every(v => v === 255), black = pixel.every(v => v === 0);
      if (mask[i + 3] !== 255 || (!white && !black)) throw Error('Use an opaque, pure black-and-white mask with no grey edges.');
      if (!white) continue;
      if (image[i + 3] !== 255) throw Error('The selected area includes transparent pixels. Exclude those pixels from the mask.');
      selected++;
      if (matches([image[i], image[i + 1], image[i + 2]], colours, tolerance)) matching++;
    }
    if (!selected) throw Error('The mask selects no pixels. This is not a pass.');
    const percent = matching * 100 / selected;
    return { selected, matching, percent, pass: matching * 100 <= limit * selected };
  }
  const api = { neutralRange, area, matches };
  if (typeof module !== 'undefined') module.exports = api;
  else root.MeasurementTools = api;
})(globalThis);
