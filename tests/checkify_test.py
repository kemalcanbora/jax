# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import partial
import unittest

from absl.testing import absltest
from absl.testing import parameterized

import jax
from jax import lax
import jax._src.test_util as jtu
from jax.config import config
from jax.experimental import checkify
import jax.numpy as jnp

config.parse_flags_with_absl()


class CheckifyTransformTests(jtu.JaxTestCase):

  @parameterized.named_parameters(jtu.cases_from_list(
      {"testcase_name": "_jit={}".format(jit), "jit": jit}
      for jit in [False, True]))
  @jtu.skip_on_devices("tpu")
  def test_jit_nan(self, jit):
    def f(x1, x2):
      y1 = jnp.sin(x1)
      y2 = jnp.sin(x2)
      return y1 + y2

    f = jax.jit(f) if jit else f
    checked_f = checkify.checkify(f, errors=checkify.float_checks)

    err, _ = checked_f(3., 4.)
    self.assertIs(err.get(), None)

    err, _ = checked_f(3., jnp.inf)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "nan generated by primitive sin")

  @parameterized.named_parameters(jtu.cases_from_list(
      {"testcase_name": "_jit={}".format(jit), "jit": jit}
      for jit in [False, True]))
  def test_jit_oob(self, jit):
    def f(x, i):
      y = jnp.sin(x)
      z = y[i]
      w = jnp.cos(z)
      return w

    f = jax.jit(f) if jit else f
    checked_f = checkify.checkify(f, errors=checkify.index_checks)

    err, _ = checked_f(jnp.arange(3), 2)
    self.assertIs(err.get(), None)

    err, _ = checked_f(jnp.arange(3), 5)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "out-of-bounds indexing")

  @parameterized.named_parameters(
      {"testcase_name": f"_updatefn={update_fn}", "update_fn": update_fn}
      for update_fn in ["set", "add", "multiply", "divide", "power", "min",
                        "max", "get"])
  def test_jit_oob_update(self, update_fn):
    def f(x, i):
      return getattr(x.at[i], update_fn)(1.)

    f = jax.jit(f)
    checked_f = checkify.checkify(f, errors=checkify.index_checks)

    err, _ = checked_f(jnp.arange(3), 2)
    self.assertIs(err.get(), None)

    err, _ = checked_f(jnp.arange(3), 3)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "out-of-bounds indexing")

  @parameterized.named_parameters(jtu.cases_from_list(
      {"testcase_name": "_jit={}".format(jit), "jit": jit}
      for jit in [False, True]))
  def test_jit_div_errors(self, jit):
    def f(x, y):
      return x/y

    f = jax.jit(f) if jit else f
    checked_f = checkify.checkify(f, errors=checkify.float_checks)

    err, _ = checked_f(jnp.ones((3,)), jnp.ones((3,)))
    self.assertIs(err.get(), None)

    err, _ = checked_f(jnp.ones((3,)), jnp.array([1, 0, 1]))
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "divided by zero")

    err, _ = checked_f(jnp.array([1, jnp.inf, 1]), jnp.array([1, jnp.inf, 1]))
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "nan generated by primitive div")

  @parameterized.named_parameters(jtu.cases_from_list(
      {"testcase_name": "_jit={}".format(jit), "jit": jit}
      for jit in [False, True]))
  @jtu.skip_on_devices("tpu")
  def test_jit_multi(self, jit):
    def f(x, i):
      y = x[i]
      z = jnp.cos(y)
      return z

    f = jax.jit(f) if jit else f
    checked_f = checkify.checkify(f, errors=checkify.automatic_checks)

    # no error
    err, _ = checked_f(jnp.array([0., jnp.inf, 2.]), 2)
    self.assertIs(err.get(), None)

    # oob error
    err, _ = checked_f(jnp.array([0., 1., 2.]), 5)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "out-of-bounds indexing")

    # nan error
    err, _ = checked_f(jnp.array([0., 1., jnp.inf]), 2)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "nan generated by primitive cos")

  @parameterized.named_parameters(jtu.cases_from_list(
      {"testcase_name": "_jit={}".format(jit), "jit": jit}
      for jit in [False, True]))
  def test_jit_ordering(self, jit):
    def f(x, i):
      y = x[i]
      z = jnp.sin(x)
      return y * z

    f = jax.jit(f) if jit else f
    checked_f = checkify.checkify(f, errors=checkify.automatic_checks)

    # both oob and nan error, but oob happens first
    err, _ = checked_f(jnp.array([0., 1., jnp.inf]), 5)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "out-of-bounds indexing")

  @jtu.skip_on_devices("tpu")
  def test_pmap_basic(self):
    if len(jax.devices()) < 2:
      raise unittest.SkipTest("requires at least 2 devices")

    @jax.pmap
    def f(x1, x2):
      y1 = jnp.sin(x1)
      y2 = jnp.sin(x2)
      return y1 + y2
    checked_f = checkify.checkify(f, errors=checkify.float_checks)

    xs = jnp.array([0., 2.])
    err, _ = checked_f(xs, xs)
    self.assertIs(err.get(), None)

    ys = jnp.array([3., jnp.inf])
    err, _ = checked_f(xs, ys)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "nan generated by primitive sin")

  @jtu.skip_on_devices("tpu")
  def test_cond_basic(self):
    @jax.jit
    def f(x):
      return lax.cond(x > 0,
                      lambda: jnp.sin(x),
                      lambda: x)

    checked_f = checkify.checkify(f, errors=checkify.float_checks)

    err, _ = checked_f(3.)
    self.assertIs(err.get(), None)

    err, _ = checked_f(jnp.inf)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "nan generated by primitive sin")

    err, _ = checked_f(-jnp.inf)
    self.assertIs(err.get(), None)

  @jtu.skip_on_devices("tpu")
  def test_scan_map(self):
    def scan_body(_, x):
      return None, jnp.sin(x)

    @jax.jit
    def f(xs):
      return lax.scan(scan_body, None, xs)

    checked_f = checkify.checkify(f, errors=checkify.float_checks)

    xs = jnp.array([0., 2.])
    err, (_, ch_outs) = checked_f(xs)
    _, outs = f(xs)
    self.assertIs(err.get(), None)
    self.assertArraysEqual(ch_outs, outs)

    xs = jnp.array([3., jnp.inf])
    err, (_, ch_outs) = checked_f(xs)
    _, outs = f(xs)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "nan generated by primitive sin")
    self.assertArraysEqual(ch_outs, outs)

  @jtu.skip_on_devices("tpu")
  def test_scan_carry(self):
    def scan_body(carry, x):
      carry = carry-1.
      possible_nan = jnp.sin(1./carry)
      return carry, x+possible_nan

    @jax.jit
    def f(carry, xs):
      return lax.scan(scan_body, carry, xs)

    checked_f = checkify.checkify(f, errors=checkify.float_checks)

    carry, xs = 3., jnp.ones((2,))
    err, (ch_out_carry, ch_outs) = checked_f(carry, xs)
    out_carry, outs = f(carry, xs)
    self.assertIs(err.get(), None)
    self.assertArraysEqual(ch_outs, outs)
    self.assertArraysEqual(ch_out_carry, out_carry)

    # error happens on first iteration
    carry, xs = 1., jnp.ones((2,))
    err, (ch_out_carry, ch_outs) = checked_f(carry, xs)
    out_carry, outs = f(carry, xs)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "divided by zero")
    self.assertArraysEqual(ch_outs, outs)
    self.assertArraysEqual(ch_out_carry, out_carry)

    # error happens on second iteration
    carry, xs = 2., jnp.ones((4,))
    err, (ch_out_carry, ch_outs) = checked_f(carry, xs)
    out_carry, outs = f(carry, xs)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "divided by zero")
    self.assertArraysEqual(ch_outs, outs)
    self.assertArraysEqual(ch_out_carry, out_carry)

  @jtu.skip_on_devices("tpu")
  def test_while_loop_body_error(self):
    def while_cond(val):
      i, _ = val
      return i < 2

    def while_body(val):
      i, x = val
      possible_nan = jnp.sin(1./i)
      return i+1., x+possible_nan

    @jax.jit
    def f(init_val):
      return lax.while_loop(while_cond, while_body, (init_val, 0.))

    checked_f = checkify.checkify(f, errors=checkify.float_checks)

    init_val = 1.
    err, ch_out = checked_f(init_val)
    out = f(init_val)
    self.assertIs(err.get(), None)
    self.assertArraysEqual(ch_out, out)

    init_val = 0.
    err, ch_out = checked_f(init_val)
    out = f(init_val)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "divided by zero")
    self.assertArraysEqual(ch_out, out)

  @jtu.skip_on_devices("tpu")
  def test_while_loop_cond_error(self):
    def while_cond(val):
      _ = jnp.sin(1./val)
      return val < 2.

    def while_body(val):
      return val+1.

    @jax.jit
    def f(init_val):
      return lax.while_loop(while_cond, while_body, init_val)

    checked_f = checkify.checkify(f, errors=checkify.float_checks)

    init_val = 1.
    err, ch_out = checked_f(init_val)
    out = f(init_val)
    self.assertIs(err.get(), None)
    self.assertArraysEqual(ch_out, out)

    init_val = 0.
    err, ch_out = checked_f(init_val)
    out = f(init_val)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "divided by zero")
    self.assertArraysEqual(ch_out, out)

  @jtu.skip_on_devices("tpu")
  def test_while_loop_cond_error_and_false(self):
    # Tests if an error is generated when cond returns False.
    def while_cond(val):
      possible_nan = jnp.sin(1./val)
      return jnp.logical_not(jnp.isnan(possible_nan))

    @jax.jit
    def f(init_val):
      return lax.while_loop(while_cond, lambda val: val-1, init_val)

    checked_f = checkify.checkify(f, errors=checkify.float_checks)

    # error on first cond
    init_val = 0.
    err, _ = checked_f(init_val)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "divided by zero")

    # error on second cond
    init_val = 1.
    err, _ = checked_f(init_val)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "divided by zero")

  @jtu.skip_on_devices("tpu")
  def test_while_loop_body_and_cond_error(self):
    def while_cond(val):
      i, cond_val, _ = val
      _ = jnp.sin(cond_val)
      return i < 2

    def while_body(val):
      i, cond_val, body_val = val
      possible_nan = jnp.cos(body_val)
      return i+1., cond_val, possible_nan

    @jax.jit
    def f(cond_val, body_val):
      return lax.while_loop(while_cond, while_body, (0., cond_val, body_val))

    checked_f = checkify.checkify(f, errors=checkify.float_checks)

    cond_val = jnp.inf
    body_val = 1.
    err, _ = checked_f(cond_val, body_val)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "nan generated by primitive sin")

    cond_val = 1.
    body_val = jnp.inf
    err, _ = checked_f(cond_val, body_val)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "nan generated by primitive cos")

    cond_val = jnp.inf
    body_val = jnp.inf
    err, _ = checked_f(cond_val, body_val)
    self.assertIsNotNone(err.get())
    # first error which occurs is in cond
    self.assertStartsWith(err.get(), "nan generated by primitive sin")

  def test_empty_enabled_errors(self):
    with self.assertRaisesRegex(ValueError, "called with an empty errors set"):
      checkify.checkify(lambda x: x, errors={})

  @parameterized.named_parameters(
      ("assert", checkify.user_checks, "must be negative!"),
      ("div", {checkify.ErrorCategory.DIV}, "divided by zero"),
      ("nan", {checkify.ErrorCategory.NAN}, "nan generated"),
      ("oob", checkify.index_checks, "out-of-bounds indexing"),
      ("automatic_checks", checkify.automatic_checks, "divided by zero"),
    )
  @jtu.skip_on_devices("tpu")
  def test_enabled_errors(self, error_set, expected_error):
    def multi_errors(x):
      x = x/0         # DIV
      x = jnp.sin(x)  # NAN
      x = x[500]      # OOB
      checkify.check(x < 0, "must be negative!")  # ASSERT
      return x

    x = jnp.ones((2,))
    err, _ = checkify.checkify(multi_errors, errors=error_set)(x)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), expected_error)

  @jtu.skip_on_devices("tpu")
  def test_post_process_call(self):
    @partial(checkify.checkify, errors=checkify.float_checks)
    def g(x):
      @jax.jit
      def f(y):
        return jnp.sin(x * y)
      return f(jnp.inf)
    err, _ = g(2.)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "nan generated by primitive sin")

  @jtu.skip_on_devices("tpu")
  def test_post_process_map(self):
    @partial(checkify.checkify, errors=checkify.float_checks)
    def g(x):
      @jax.pmap
      def f(y):
        return jnp.sin(x * y)
      return f(jnp.array([jnp.inf]))[0]
    err, _ = g(2.)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), 'nan generated by primitive sin')

  @jtu.skip_on_devices("tpu")
  def test_custom_jvp(self):
    @jax.custom_jvp
    def sin(x):
      return jnp.sin(x)

    @sin.defjvp
    def sin_jvp(primals, tangents):
      (x,), (xdot,) = primals, tangents
      return sin(x), jnp.cos(x) * xdot

    f = checkify.checkify(sin, errors=checkify.float_checks)

    err, y = f(3.)
    self.assertIsNone(err.get())
    err, y = f(jnp.inf)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), 'nan generated by primitive sin')

    # When we hit the custom jvp rule with jvp-of-checkify, no checks are added.
    (err, y), (errdot, ydot) = jax.jvp(f, (3.,), (1.,))  # doesn't crash
    self.assertIsNone(err.get())  # no error
    self.assertEmpty(err.msgs)    # and no checks were added!
    self.assertEmpty(errdot.msgs)
    y_expected, ydot_expected = jax.jvp(jnp.sin, (3.,), (1.,))
    self.assertAllClose(y, y_expected)
    self.assertAllClose(ydot, ydot_expected)

    # Grad-of-checkify doesn't crash either.
    x_bar = jax.grad(lambda x: f(x)[1])(3.)
    self.assertAllClose(x_bar, jnp.cos(3.))

    # Checkify-of-jvp adds checks (unlike jvp-of-checkify above).
    g = checkify.checkify(lambda x, xdot: jax.jvp(sin, (x,), (xdot,)),
                          errors=checkify.float_checks)
    err, (y, ydot) = g(3., 1.)  # doesn't crash
    self.assertIsNone(err.get())  # no error
    self.assertNotEmpty(err.msgs) # but checks were added!
    self.assertAllClose(y, jnp.sin(3.))
    self.assertAllClose(ydot, jnp.cos(3.))
    err, _ = g(jnp.inf, 1.)
    self.assertIsNotNone(err.get())  # yes error
    self.assertStartsWith(err.get(), 'nan generated by primitive sin')

  @jtu.skip_on_devices("tpu")
  def test_custom_vjp(self):
    @jax.custom_vjp
    def sin(x):
      return jnp.sin(x)

    def sin_fwd(x):
      return jnp.sin(x), 2. * x
    def sin_bwd(x2, g):
      return jnp.cos(x2 / 2.) * g,
    sin.defvjp(sin_fwd, sin_bwd)

    f = checkify.checkify(sin, errors=checkify.float_checks)

    # no differentiation, no error
    err, y = f(3.)
    self.assertIsNone(err.get())

    # no differentiation, yes error
    err, y = f(jnp.inf)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), 'nan generated by primitive sin')

    # When we hit the custom vjp rule with vjp-of-checkify, no checks are added.
    (err, y), f_vjp = jax.vjp(f, 3.)
    self.assertIsNone(err.get())  # no error
    self.assertEmpty(err.msgs)    # and no checks were added!

    # Checkify-of-vjp adds checks (unlike vjp-of-checkify above).
    err, y = checkify.checkify(jax.grad(sin), errors=checkify.float_checks)(3.)
    self.assertIsNone(err.get())   # no error
    self.assertNotEmpty(err.msgs)  # but checks were added!
    err, y = checkify.checkify(jax.grad(sin),
                               errors=checkify.float_checks)(jnp.inf)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), 'nan generated by primitive sin')


class AssertPrimitiveTests(jtu.JaxTestCase):

  def test_assert_primitive_impl(self):
    def f():
      checkify.check(False, "hi")

    with self.assertRaisesRegex(ValueError, "hi"):
      f()

  def test_assert_primitive_(self):
    @jax.jit
    def f():
      checkify.check(False, "hi")

    with self.assertRaisesRegex(Exception, "can't be staged"):
      f()

  def test_assert_discharging(self):
    @checkify.checkify
    def f(x):
      checkify.check(x > 0, "must be positive!")
      return jnp.log(x)

    err, _ = f(1.)
    self.assertIsNone(err.get())

    err, _ = f(0.)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "must be positive")

    f = jax.jit(f)

    err, _ = f(1.)
    self.assertIsNone(err.get())

    err, _ = f(0.)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "must be positive")

  def test_check_error(self):
    def f(pred):  # note: data dependence needed!
      checkify.check_error(checkify.Error(~pred, 0, {0: "hi"}))

    with self.assertRaisesRegex(ValueError, "hi"):
      f(False)

    f = checkify.checkify(f)
    err, none = f(False)

    self.assertIsNone(none)
    self.assertIsNotNone(err.get())
    self.assertStartsWith(err.get(), "hi")

  def test_discharge_recharge(self):
    def ejit(f):
      f = checkify.checkify(f)
      f = jax.jit(f)
      def jitted_f(*args):
        err, out = f(*args)
        checkify.check_error(err)
        return out
      return jitted_f

    @ejit
    def f(pred):
      assert python_should_be_running
      checkify.check(pred, "foo")

    python_should_be_running = True
    f(True)

    python_should_be_running = False
    f(True)
    with self.assertRaisesRegex(ValueError, "foo"):
      f(False)

  def test_cond_of_named_call(self):
    def g(x):
      branch = jax.named_call(lambda x: x)
      out = jax.lax.cond(True, branch, branch, x)
      return out

    checkify.checkify(g)(0.)  # does not crash

if __name__ == "__main__":
  absltest.main(testLoader=jtu.JaxTestLoader())
