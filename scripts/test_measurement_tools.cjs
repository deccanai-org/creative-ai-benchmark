const test = require('node:test');
const assert = require('node:assert/strict');
const { neutralRange, area, matches } = require('../docs/gatsby-v7/annotation-pilot/measurement-tools.js');
test('neutral range accepts endpoints and midpoint', () => {
  for (const rgb of [[217,221,222],[242,238,231],[229.5,229.5,226.5]]) assert.equal(neutralRange(rgb),true);
});
test('neutral range allows exactly five, not six', () => {
  assert.equal(neutralRange([212,216,217]),true);
  assert.equal(neutralRange([211,216,217]),false);
});
test('neutral range rejects colours that only match independent channel bounds', () => {
  assert.equal(neutralRange([217,238,231]),false);
  assert.equal(neutralRange([0,0,0]),false);
  assert.throws(()=>neutralRange([256,0,0]));
});
const image = count => new Uint8ClampedArray(Array.from({length:100},(_,i)=>i<count?[50,60,70,255]:[200,210,220,255]).flat());
const mask = () => new Uint8ClampedArray(400).fill(255);
test('area threshold accepts 5% and rejects 6%', () => {
  assert.equal(area(image(5),mask(),[[50,60,70]],5,5).pass,true);
  assert.equal(area(image(6),mask(),[[50,60,70]],5,5).pass,false);
});
test('area uses unrounded values', () => {
  const m=mask();m.set([0,0,0,255],396);
  assert.equal(area(image(5),m,[[50,60,70]],5,5).pass,false);
});
test('area rejects empty, grey or transparent masks', () => {
  const m=new Uint8ClampedArray(Array.from({length:100},()=>[0,0,0,255]).flat());
  assert.throws(()=>area(image(5),m,[[50,60,70]],5,5),/no pixels/);
  m.set([128,128,128,255],0);assert.throws(()=>area(image(5),m,[[50,60,70]],5,5),/pure black/);
  m.set([255,255,255,0],0);assert.throws(()=>area(image(5),m,[[50,60,70]],5,5),/opaque/);
});
test('area rejects transparent selected artwork and mismatched arrays', () => {
  const a=image(5);a[3]=0;assert.throws(()=>area(a,mask(),[[50,60,70]],5,5),/transparent/);
  assert.throws(()=>area(a,new Uint8ClampedArray(4),[[50,60,70]],5,5),/dimensions/);
});
test('colour tolerance is inclusive and duplicate colours count once', () => {
  assert.equal(matches([55,55,75],[[50,60,70]],5),true);
  assert.equal(matches([56,55,75],[[50,60,70]],5),false);
  assert.equal(area(image(5),mask(),[[50,60,70],[50,60,70]],5,5).matching,5);
});
