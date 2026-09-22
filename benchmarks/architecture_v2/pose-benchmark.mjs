import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const THREE = await import(pathToFileURL(resolve("apps/web/node_modules/three/build/three.module.js")).href);
const cases = [1, 23];
const landmarksPerSubject = 29;
const providerEdges = 28;
const displayCueEdges = 13;
const segmentEdges = 6;
const analyticalAngleArcs = 6;
const articulationArcs = 14;
const iterations = Number(process.env.RES109_POSE_ITERATIONS ?? 20);

function quantile(values, probability) {
  const sorted = [...values].sort((left, right) => left - right);
  const position = (sorted.length - 1) * probability;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

function coordinates(subjects) {
  const values = new Float32Array(subjects * landmarksPerSubject * 3);
  for (let index = 0; index < values.length; index += 3) {
    values[index] = Math.sin(index / 11);
    values[index + 1] = Math.cos(index / 17);
    values[index + 2] = Math.sin(index / 23);
  }
  return values;
}

function currentScene(subjects) {
  const scene = new THREE.Scene();
  const objects = [];
  for (let subject = 0; subject < subjects; subject += 1) {
    for (let landmark = 0; landmark < landmarksPerSubject; landmark += 1) {
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.026, 16, 16), new THREE.MeshStandardMaterial());
      scene.add(mesh);
      objects.push(mesh);
    }
    for (let landmark = 0; landmark < landmarksPerSubject; landmark += 1) {
      const error = new THREE.Mesh(new THREE.SphereGeometry(0.04, 10, 10), new THREE.MeshBasicMaterial({ transparent: true }));
      scene.add(error);
      objects.push(error);
    }
    for (const edgeCount of [providerEdges, displayCueEdges, segmentEdges, analyticalAngleArcs, articulationArcs]) {
      for (let edge = 0; edge < edgeCount; edge += 1) {
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(1, 1, 1)]), new THREE.LineBasicMaterial());
        scene.add(line);
        objects.push(line);
      }
    }
  }
  return { scene, objects };
}

function optimizedScene(subjects) {
  const scene = new THREE.Scene();
  const jointCount = subjects * landmarksPerSubject;
  const jointGeometry = new THREE.SphereGeometry(0.026, 8, 8);
  const jointInstances = new THREE.InstancedMesh(jointGeometry, new THREE.MeshStandardMaterial(), jointCount);
  scene.add(jointInstances);
  const errorInstances = new THREE.InstancedMesh(new THREE.SphereGeometry(0.04, 6, 6), new THREE.MeshBasicMaterial({ transparent: true }), jointCount);
  scene.add(errorInstances);
  const lineObjects = [];
  for (const edgeCount of [providerEdges, displayCueEdges, segmentEdges, analyticalAngleArcs, articulationArcs]) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(subjects * edgeCount * 6), 3));
    const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial());
    scene.add(lines);
    lineObjects.push(lines);
  }
  return { scene, jointInstances, errorInstances, lineObjects };
}

function updateCurrent(objects, values) {
  let valueIndex = 0;
  for (const object of objects) {
    if (object.isMesh) {
      object.position.set(values[valueIndex] ?? 0, values[valueIndex + 1] ?? 0, values[valueIndex + 2] ?? 0);
      valueIndex = (valueIndex + 3) % values.length;
    } else {
      const position = object.geometry.attributes.position;
      const array = position.array;
      for (let index = 0; index < array.length; index += 1) array[index] = values[(index + valueIndex) % values.length] ?? 0;
      position.needsUpdate = true;
    }
  }
}

function updateOptimized(optimized, values) {
  const matrix = new THREE.Matrix4();
  for (let index = 0; index < optimized.jointInstances.count; index += 1) {
    const offset = (index * 3) % values.length;
    matrix.makeTranslation(values[offset] ?? 0, values[offset + 1] ?? 0, values[offset + 2] ?? 0);
    optimized.jointInstances.setMatrixAt(index, matrix);
    optimized.errorInstances.setMatrixAt(index, matrix);
  }
  optimized.jointInstances.instanceMatrix.needsUpdate = true;
  optimized.errorInstances.instanceMatrix.needsUpdate = true;
  for (const line of optimized.lineObjects) {
    const array = line.geometry.attributes.position.array;
    for (let index = 0; index < array.length; index += 1) array[index] = values[index % values.length] ?? 0;
    line.geometry.attributes.position.needsUpdate = true;
  }
}

function measure(subjects) {
  const values = coordinates(subjects);
  const currentStartHeap = process.memoryUsage().heapUsed;
  const current = currentScene(subjects);
  const currentBuildHeap = process.memoryUsage().heapUsed;
  const currentDurations = [];
  for (let index = 0; index < iterations; index += 1) {
    const started = performance.now();
    updateCurrent(current.objects, values);
    currentDurations.push(performance.now() - started);
  }
  const optimizedStartHeap = process.memoryUsage().heapUsed;
  const optimized = optimizedScene(subjects);
  const optimizedBuildHeap = process.memoryUsage().heapUsed;
  const optimizedDurations = [];
  for (let index = 0; index < iterations; index += 1) {
    const started = performance.now();
    updateOptimized(optimized, values);
    optimizedDurations.push(performance.now() - started);
  }
  const currentObjects = current.scene.children.length;
  const optimizedObjects = optimized.scene.children.length;
  const currentDrawCalls = currentObjects;
  const optimizedDrawCalls = optimizedObjects;
  const currentP95 = iterations >= 20 ? quantile(currentDurations, 0.95) : null;
  const optimizedP95 = iterations >= 20 ? quantile(optimizedDurations, 0.95) : null;
  return {
    subjects,
    landmarks_per_subject: landmarksPerSubject,
    current: {
      objects: currentObjects,
      draw_calls: currentDrawCalls,
      frame_update_ms_median: quantile(currentDurations, 0.5),
      frame_update_ms_p95: iterations >= 20 ? quantile(currentDurations, 0.95) : null,
      frame_update_ms_max_observed: Math.max(...currentDurations),
      heap_delta_bytes: currentBuildHeap - currentStartHeap,
      picking_targets: subjects * landmarksPerSubject,
    },
    optimized: {
      objects: optimizedObjects,
      draw_calls: optimizedDrawCalls,
      frame_update_ms_median: quantile(optimizedDurations, 0.5),
      frame_update_ms_p95: iterations >= 20 ? quantile(optimizedDurations, 0.95) : null,
      frame_update_ms_max_observed: Math.max(...optimizedDurations),
      heap_delta_bytes: optimizedBuildHeap - optimizedStartHeap,
      picking_targets: subjects * landmarksPerSubject,
      typed_buffer_mutation: true,
    },
    reduction: {
      object_factor: currentObjects / optimizedObjects,
      draw_call_factor: currentDrawCalls / optimizedDrawCalls,
      update_factor: currentP95 !== null && optimizedP95 !== null
        ? currentP95 / Math.max(optimizedP95, 0.000001)
        : null,
    },
  };
}

const output = process.env.RES109_POSE_OUTPUT ?? "benchmarks/architecture_v2/pose-receipt.json";
const receipt = {
  schema_version: "architecture-v2-pose-benchmark-1",
  workload: "23 subjects x 29 landmarks with provider/display/analytical layers and error radii",
  iterations,
  cases: cases.map(measure),
  note: "This headless Three scene benchmark measures scene-graph/object and typed-buffer update costs. Browser GPU timings are recorded by the WebGL/WebGPU probe separately.",
};
await import("node:fs/promises").then(({ writeFile }) => writeFile(output, JSON.stringify(receipt, null, 2) + "\n"));
console.log(JSON.stringify({ output, cases: receipt.cases.length }));
