/* Publishes the three.js ES-module build to the classic page script: window.THREE, window.THREE_ADDONS,
   then the 'three-ready' event that resolves window.threeReady. */
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { SMAAPass } from 'three/addons/postprocessing/SMAAPass.js';
import { HDRLoader } from 'three/addons/loaders/HDRLoader.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

window.THREE = THREE;
window.THREE_ADDONS = { EffectComposer, RenderPass, GTAOPass, UnrealBloomPass, OutputPass, SMAAPass, HDRLoader, RectAreaLightUniformsLib, RoomEnvironment };
window.dispatchEvent(new Event('three-ready'));
