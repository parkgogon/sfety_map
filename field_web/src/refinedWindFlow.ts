import { sampleWindVectorField, type WindParticle, type WindVectorField } from "./windParticleField";

/** Visual speed in CSS pixels per second; the field's u/v and speed stay unchanged. */
export function refinedWindSpeed(speed: number): number {
  return Number.isFinite(speed) && speed >= 0.0001 ? 7 + 8 * Math.sqrt(speed) : 0;
}

export function refinedWindCount(width: number, height: number): number {
  return Math.min(600, Math.max(80, Math.round(Math.max(0, width * height) * 1 / 1050)));
}

export function refinedWindTail(speed: number): number {
  return Number.isFinite(speed) && speed >= 0.0001 ? 12 + 4 * Math.sqrt(speed) : 0;
}

export function drawRefinedWindFlow(
  context: CanvasRenderingContext2D, field: WindVectorField, particles: WindParticle[], staticMode = false, deltaSeconds = 1 / 30,
) {
  context.save();
  if (staticMode) {
    context.clearRect(0, 0, field.width, field.height);
  } else {
    // Fade each particle's actual trajectory on the transparent particle canvas.
    context.globalCompositeOperation = "destination-in";
    context.fillStyle = `rgba(0,0,0,${Math.exp(-deltaSeconds / 0.48)})`;
    context.fillRect(0, 0, field.width, field.height);
    context.globalCompositeOperation = "source-over";
  }
  context.lineCap = "round";
  let visible = false;
  for (const p of particles) {
    let x = p.previousX, y = p.previousY;
    if (staticMode) {
      const vector = sampleWindVectorField(field, p.x, p.y);
      if (!vector || vector.speed < 0.0001) continue;
      const length = refinedWindTail(vector.speed) * 0.65;
      x = p.x - vector.dx / vector.speed * length;
      y = p.y - vector.dy / vector.speed * length;
    }
    if (x === p.x && y === p.y) continue;
    if (!visible) context.beginPath();
    context.moveTo(x, y);
    context.lineTo(p.x, p.y);
    visible = true;
  }
  if (visible) {
    context.lineWidth = 1.15;
    context.strokeStyle = "rgba(247,253,255,.88)";
    context.stroke();
  }
  context.restore();
}
