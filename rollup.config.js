import resolve from 'rollup-plugin-node-resolve';
import commonjs from 'rollup-plugin-commonjs';
import copy from 'rollup-plugin-copy';
import {terser} from "rollup-plugin-terser";

const dev = process.env.ROLLUP_WATCH === 'true';

export default {
  input: 'index.js',
  output: {
    file: 'static/js/index.js',
    format: 'iife'
  },
  plugins: [
    resolve(),
    commonjs(),
    !dev && terser(),
    copy({
      targets: [
        './node_modules/bootstrap/dist/css/bootstrap.min.css',
      ],
      outputFolder: 'static/css',
      warnOnNonExist: true
    }),
  ],
};
