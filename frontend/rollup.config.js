import process from 'node:process';
import postcss from 'rollup-plugin-postcss';
import postcssLogical from 'postcss-logical';
import autoprefixer from 'autoprefixer';
import {replacePlugin} from 'rolldown/plugins';
import copy from 'rollup-plugin-copy'
import license from 'rollup-plugin-license';
import {getBabelOutputPlugin} from '@rollup/plugin-babel';

const dev = process.env.ROLLUP_WATCH === 'true';

export default {
  input: 'index.js',
  output: {
    file: '../app/static/index.js',
    format: 'es',
    minify: !dev,
  },
  plugins: [
    replacePlugin({
      'process.env.NODE_ENV': JSON.stringify('production'),
    }, {
      preventAssignment: true,
    }),
    postcss({
      extract: 'index.css',
      minimize: true,
      use: {
        sass: {
          silenceDeprecations: ['import', 'color-functions', 'global-builtin', 'legacy-js-api']
        }
      },
      plugins: [
        postcssLogical(),
        autoprefixer(),
      ]
    }),
    license({
        banner: {
            commentStyle: 'ignored',
            content: `
Dependencies:
<% _.forEach(dependencies, function (dependency) { if (dependency.name) { %>
<%= dependency.name %>: <%= dependency.license %><% }}) %>
`,
        },
        thirdParty: {
            allow: {
                test: 'MIT',
                failOnUnlicensed: true,
                failOnViolation: true,
            },
        },
    }),
    copy({
        targets: [
          { src: 'node_modules/@fontsource/roboto/files/roboto-latin-400-normal.woff2', dest: '../app/static/fonts' },
          { src: 'node_modules/@fontsource/roboto/files/roboto-latin-700-normal.woff2', dest: '../app/static/fonts' },
        ]
    }),
    !dev && getBabelOutputPlugin({
        compact: false,
        presets: [[
            '@babel/preset-env', {
                loose: true,
                bugfixes: true,
                modules: false,
                targets: {
                    esmodules: true
                }
            }
        ]],
    }),
  ],
};
