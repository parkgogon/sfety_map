import { sampleWindVectorField, type WindParticle, type WindVectorField } from "./windParticleField";

/** Adopted option A: visual values only; the field's u/v and speed stay unchanged. */
export function refinedWindSpeed(speed: number): number {
  return Number.isFinite(speed) && speed >= 0.0001 ? 9 + 6 * Math.sqrt(speed) : 0;
}

export function refinedWindCount(width: number, height: number): number {
  return Math.min(600, Math.max(80, Math.round(Math.max(0, width * height) * 135 / 300_000)));
}

export function refinedWindTail(speed: number): number {
  return Number.isFinite(speed) && speed >= 0.0001 ? 12 + 4 * Math.sqrt(speed) : 0;
}

export function drawRefinedWindFlow(
  context: CanvasRenderingContext2D, field: WindVectorField, particles: WindParticle[], staticMode = false,
) {
  context.clearRect(0, 0, field.width, field.height);
  context.save();
  context.lineCap = "round";
  for (const p of particles) {
    const vector = sampleWindVectorField(field, p.x, p.y);
    if (!vector || vector.speed < 0.0001) continue;
    const tail = refinedWindTail(vector.speed);
    const x = p.x - vector.dx / vector.speed * tail;
    const y = p.y - vector.dy / vector.speed * tail;
    context.globalAlpha = staticMode ? 1 : Math.max(0.2,
      Math.min(1, p.ageSeconds / 0.4, (p.maxAgeSeconds - p.ageSeconds) / 0.5));
    context.beginPath();
    context.moveTo(x, y); context.lineTo(p.x, p.y);
    context.lineWidth = 3.2; context.strokeStyle = "rgba(255,255,255,.72)"; context.stroke();
    const gradient = context.createLinearGradient(x, y, p.x, p.y);
    gradient.addColorStop(0, "rgba(22,86,106,.05)");
    gradient.addColorStop(0.45, "rgba(32,101,121,.82)");
    gradient.addColorStop(1, "#145268");
    context.lineWidth = 1.5; context.strokeStyle = gradient; context.stroke();
    context.fillStyle = "#f8ffff"; context.beginPath();
    context.arc(p.x, p.y, 0.85, 0, Math.PI * 2); context.fill();
  }
  context.restore();
}
