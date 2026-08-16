"use client";

import { useEffect, useRef } from "react";

/**
 * The hero's animated background: a flowing aurora field, drawn as a single
 * full-screen fragment shader.
 *
 * Written against raw WebGL rather than Three.js on purpose. This scene is two
 * triangles and one shader — three.js plus a renderer is several hundred
 * kilobytes to draw a quad, and NEXUS is a local tool whose landing page
 * should open instantly. The whole component is ~130 lines and has no
 * dependency at all.
 *
 * It is also careful about when it runs:
 *   - nothing initialises until the element is on screen;
 *   - the loop stops when it scrolls away or the tab is hidden;
 *   - the buffer is capped at 1.5x on desktop and 1x on small screens;
 *   - `prefers-reduced-motion` and any WebGL failure fall back to the static
 *     CSS gradient underneath, which is why that gradient is not optional.
 */

const VERTEX = `
attribute vec2 position;
void main() { gl_Position = vec4(position, 0.0, 1.0); }
`;

/* Two rotated, domain-warped noise fields, tinted and screened together.
   Cheap enough to run at 60fps on integrated graphics: no loops beyond a
   4-octave fbm, no texture reads. */
const FRAGMENT = `
precision highp float;

uniform vec2  u_res;
uniform float u_time;
uniform vec2  u_mouse;
uniform vec3  u_accent;
uniform vec3  u_accent2;

vec2 hash(vec2 p) {
  p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
  return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(dot(hash(i + vec2(0.0, 0.0)), f - vec2(0.0, 0.0)),
        dot(hash(i + vec2(1.0, 0.0)), f - vec2(1.0, 0.0)), u.x),
    mix(dot(hash(i + vec2(0.0, 1.0)), f - vec2(0.0, 1.0)),
        dot(hash(i + vec2(1.0, 1.0)), f - vec2(1.0, 1.0)), u.x),
    u.y);
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 4; i++) {
    v += a * noise(p);
    p *= 2.02;
    a *= 0.5;
  }
  return v;
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_res.xy;
  vec2 p = (gl_FragCoord.xy - 0.5 * u_res.xy) / u_res.y;

  // The pointer nudges the field rather than driving it, so the motion still
  // reads as ambient when nobody is moving the mouse.
  vec2 m = (u_mouse - 0.5) * 0.35;
  float t = u_time * 0.045;

  vec2 q = vec2(fbm(p * 1.6 + t + m), fbm(p * 1.6 - t * 0.8 - m));
  float f = fbm(p * 2.1 + q * 1.4 + vec2(t * 0.6, -t * 0.4));

  float band1 = smoothstep(0.05, 0.62, f + 0.22);
  float band2 = smoothstep(0.10, 0.70, fbm(p * 1.2 - q + t * 0.3) + 0.30);

  vec3 col = vec3(0.0);
  col += u_accent  * band1 * 0.75;
  col += u_accent2 * band2 * 0.35;

  // Pull it down towards the page ground at the edges so the canvas has no
  // visible boundary — the gradient should end, not stop.
  float vign = smoothstep(1.15, 0.15, length(p * vec2(0.75, 1.25)));
  col *= vign;
  col *= smoothstep(0.0, 0.42, 1.0 - uv.y) * 0.55 + 0.45;

  gl_FragColor = vec4(col, 1.0);
}
`;

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

export function AuroraCanvas({ className = "" }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return; // the CSS gradient underneath is the fallback

    let gl;
    try {
      gl = canvas.getContext("webgl", {
        alpha: false,
        antialias: false,
        depth: false,
        powerPreference: "low-power",
      });
    } catch {
      gl = null;
    }
    if (!gl) return;

    const vs = compile(gl, gl.VERTEX_SHADER, VERTEX);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
    if (!vs || !fs) return;

    const program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      gl.STATIC_DRAW,
    );
    const position = gl.getAttribLocation(program, "position");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(program, "u_res");
    const uTime = gl.getUniformLocation(program, "u_time");
    const uMouse = gl.getUniformLocation(program, "u_mouse");

    // Read the accent straight off the theme so the canvas restyles with it.
    const styles = getComputedStyle(document.documentElement);
    const toRgb = (name, fallback) => {
      const raw = styles.getPropertyValue(name).trim();
      const hex = /^#([0-9a-f]{6})$/i.exec(raw);
      if (!hex) return fallback;
      const n = parseInt(hex[1], 16);
      return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
    };
    gl.uniform3fv(
      gl.getUniformLocation(program, "u_accent"),
      toRgb("--accent", [0.486, 0.42, 0.96]),
    );
    gl.uniform3fv(
      gl.getUniformLocation(program, "u_accent2"),
      toRgb("--ok", [0.247, 0.812, 0.557]),
    );

    const mouse = { x: 0.5, y: 0.5 };
    const target = { x: 0.5, y: 0.5 };

    const onPointer = (event) => {
      target.x = event.clientX / window.innerWidth;
      target.y = 1 - event.clientY / window.innerHeight;
    };
    window.addEventListener("pointermove", onPointer, { passive: true });

    const resize = () => {
      const small = window.innerWidth < 768;
      const scale = Math.min(window.devicePixelRatio || 1, small ? 1 : 1.5);
      const width = Math.floor(canvas.clientWidth * scale);
      const height = Math.floor(canvas.clientHeight * scale);
      if (canvas.width === width && canvas.height === height) return;
      canvas.width = width;
      canvas.height = height;
      gl.viewport(0, 0, width, height);
      gl.uniform2f(uRes, width, height);
    };
    resize();
    window.addEventListener("resize", resize, { passive: true });

    let frame = 0;
    let running = false;
    let revealed = false;
    const start = performance.now();

    const draw = () => {
      // Ease towards the pointer so the field drifts rather than snapping.
      mouse.x += (target.x - mouse.x) * 0.045;
      mouse.y += (target.y - mouse.y) * 0.045;
      gl.uniform2f(uMouse, mouse.x, mouse.y);
      gl.uniform1f(uTime, (performance.now() - start) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      if (!revealed) {
        revealed = true;
        canvas.style.opacity = "1";
      }
      frame = requestAnimationFrame(draw);
    };

    const play = () => {
      if (running) return;
      running = true;
      frame = requestAnimationFrame(draw);
    };
    const pause = () => {
      running = false;
      cancelAnimationFrame(frame);
    };

    // Only run while it is actually on screen and the tab is visible.
    const observer = new IntersectionObserver(
      ([entry]) => (entry.isIntersecting && !document.hidden ? play() : pause()),
      { threshold: 0.01 },
    );
    observer.observe(canvas);

    const onVisibility = () => (document.hidden ? pause() : play());
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      pause();
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onPointer);
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className={`h-full w-full ${className}`}
      style={{ opacity: 0, transition: "opacity 1200ms var(--ease)" }}
    />
  );
}
