# From https://github.com/CensoredUsername/codegen
"""
    codegen
    ~~~~~~~

    Extension to ast that allow ast -> python code generation.

    :copyright: Copyright 2008 by Armin Ronacher.
    :license: BSD.

    Copyright (c) 2008, Armin Ronacher
    All rights reserved.

    Redistribution and use in source and binary forms, with or without modification,
    are permitted provided that the following conditions are met:

    - Redistributions of source code must retain the above copyright notice, this list of
      conditions and the following disclaimer.
    - Redistributions in binary form must reproduce the above copyright notice, this list of
      conditions and the following disclaimer in the documentation and/or other materials
      provided with the distribution.
    - Neither the name of the <ORGANIZATION> nor the names of its contributors may be used to
      endorse or promote products derived  from this software without specific prior written
      permission.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
    IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
    FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
    CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
    DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
    DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
    IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF
    THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import sys
PY3 = sys.version_info >= (3, 0)
# These might not exist, so we put them equal to NoneType
Try = TryExcept = TryFinally = YieldFrom = MatMult = Await = type(None)

from ast import *

class Sep(object):
    # Performs the common pattern of returning a different symbol the first
    # time the object is called
    def __init__(self, last, first=''):
        self.last = last
        self.first = first
        self.begin = True
    def __call__(self):
        if self.begin:
            self.begin = False
            return self.first
        return self.last

def to_source(node, indent_with=' ' * 4, add_line_information=False, correct_line_numbers=False):
    """This function can convert a node tree back into python sourcecode.
    This is useful for debugging purposes, especially if you're dealing with
    custom asts not generated by python itself.

    It could be that the sourcecode is evaluable when the AST itself is not
    compilable / evaluable.  The reason for this is that the AST contains some
    more data than regular sourcecode does, which is dropped during
    conversion.

    Each level of indentation is replaced with `indent_with`.  Per default this
    parameter is equal to four spaces as suggested by PEP 8, but it might be
    adjusted to match the application's styleguide.

    If `add_line_information` is set to `True` comments for the line numbers
    of the nodes are added to the output.  This can be used to spot wrong line
    number information of statement nodes.
    """
    if correct_line_numbers:
        if hasattr(node, 'lineno'):
            return SourceGenerator(indent_with, add_line_information, True, node.lineno).process(node)
        else:
            return SourceGenerator(indent_with, add_line_information, True).process(node)
    else:
        return SourceGenerator(indent_with, add_line_information).process(node)


class SourceGenerator(NodeVisitor):
    """This visitor is able to transform a well formed syntax tree into python
    sourcecode.  For more details have a look at the docstring of the
    `node_to_source` function.
    """

    COMMA = ', '
    COLON = ': '
    ASSIGN = ' = '
    SEMICOLON = '; '
    ARROW = ' -> '

    BOOLOP_SYMBOLS = {
        And:        (' and ', 5),
        Or:         (' or ',  4)
    }

    BINOP_SYMBOLS = {
        Add:        (' + ',  12),
        Sub:        (' - ',  12),
        Mult:       (' * ',  13),
        MatMult:    (' @ ',  13),
        Div:        (' / ',  13),
        FloorDiv:   (' // ', 13),
        Mod:        (' % ',  13),
        Pow:        (' ** ', 15),
        LShift:     (' << ', 11),
        RShift:     (' >> ', 11),
        BitOr:      (' | ',  8),
        BitAnd:     (' & ',  10),
        BitXor:     (' ^ ',  9)
    }

    CMPOP_SYMBOLS = {
        Eq:         (' == ',     7),
        Gt:         (' > ',      7),
        GtE:        (' >= ',     7),
        In:         (' in ',     7),
        Is:         (' is ',     7),
        IsNot:      (' is not ', 7),
        Lt:         (' < ',      7),
        LtE:        (' <= ',     7),
        NotEq:      (' != ',     7),
        NotIn:      (' not in ', 7)
    }

    UNARYOP_SYMBOLS = {
        Invert:     ('~',    14),
        Not:        ('not ', 6),
        UAdd:       ('+',    14),
        USub:       ('-',    14)
    }

    BLOCK_NODES = (If, For, While, With, Try, TryExcept, TryFinally,
                   FunctionDef, ClassDef)

    def __init__(self, indent_with, add_line_information=False, correct_line_numbers=False, line_number=1):
        self.result = []
        self.indent_with = indent_with
        self.add_line_information = add_line_information
        self.indentation = 0
        self.new_lines = 0

        # precedence_stack: what precedence level are we on, could we safely newline before and is this operator left-to-right
        self.precedence_stack = [[0, False, None]]

        self.correct_line_numbers = correct_line_numbers
        # The current line number we *think* we are on. As in it's most likely
        # the line number of the last node we passed which can differ when
        # the ast is broken
        self.line_number = line_number
        # Can we insert a newline here without having to escape it?
        # (are we between delimiting characters)
        self.can_newline = False
        # after a colon, we don't have to print a semi colon. set to 1 when self.body() is called,
        # set to 2 or 0 when it's actually used. set to 0 at the end of the body
        self.after_colon = 0
        # reset by a call to self.newline, set by the first call to write() afterwards
        # determines if we have to print the newlines and indent
        self.indented = False
        # the amount of newlines to be printed
        self.newlines = 0
        # force the printing of a proper newline (and not a semicolon)
        self.force_newline = False

    def process(self, node):
        self.visit(node)
        result = ''.join(self.result)
        self.result = []
        return result

    # Precedence management

    def prec_start(self, value, ltr=None):
        newline = self.can_newline
        if value < self.precedence_stack[-1][0]:
            self.write('(')
            self.can_newline = True
        if ltr == False:
            value += 1
        self.precedence_stack.append([value, newline, ltr])

    def prec_middle(self, level=None):
        if level is not None:
            self.precedence_stack[-1][0] = level
        elif self.precedence_stack[-1][2]:
            self.precedence_stack[-1][0] += 1
        elif self.precedence_stack[-1][2] is False:
            self.precedence_stack[-1][0] -= 1

    def prec_end(self):
        precedence, newline, ltr = self.precedence_stack.pop()
        if ltr:
            precedence -= 1
        if precedence < self.precedence_stack[-1][0]:
            self.write(')')
            self.can_newline = newline

    def paren_start(self, symbol='('):
        self.precedence_stack.append([0, self.can_newline, None])
        self.write(symbol)
        self.can_newline = True

    def paren_end(self, symbol=')'):
        _, self.can_newline, _ = self.precedence_stack.pop()
        self.write(symbol)

    # convenience functions

    def write(self, x):
        # ignore empty writes
        if not x:
            return

        # Before we write, we must check if newlines have been queued.
        # If this is the case, we have to handle them properly
        if self.correct_line_numbers:
            if not self.indented:
                self.new_lines = max(self.new_lines, 1 if self.force_newline else 0)
                self.force_newline = False

                if self.new_lines:
                    # we have new lines to print
                    if self.after_colon == 2:
                        self.result.append(';'+'\\\n' * self.new_lines)
                    else:
                        self.after_colon = 0
                        self.result.append('\n' * self.new_lines)
                    self.result.append(self.indent_with * self.indentation)
                elif self.after_colon == 1:
                    # we're directly after a block-having statement and can write on the same line
                    self.after_colon = 2
                    self.result.append(' ')
                elif self.result:
                    # we're after any statement. or at the start of the file
                    self.result.append(self.SEMICOLON)
                self.indented = True
            elif self.new_lines > 0:
                if self.can_newline:
                    self.result.append('\n' * self.new_lines)
                    self.result.append(self.indent_with * (self.indentation + 1))
                else:
                    self.result.append('\\\n' * self.new_lines)
                    self.result.append(self.indent_with * (self.indentation + 1))
            self.new_lines = 0


        elif self.new_lines:
            # normal behaviour
            self.result.append('\n' * self.new_lines)
            self.result.append(self.indent_with * self.indentation)
            self.new_lines = 0
        self.result.append(x)

    def newline(self, node=None, extra=0, force=False):
        if not self.correct_line_numbers:
            self.new_lines = max(self.new_lines, 1 + extra)
            if not self.result:
                self.new_lines = 0
            if node is not None and self.add_line_information:
                self.write('# line: %s' % node.lineno)
                self.new_lines = 1
        else:
            if extra:
                #Ignore extra
                return

            self.indented = False

            if node is None:
                # else/finally statement. insert one true newline. body is implicit
                self.force_newline = True
                self.new_lines += 1
                self.line_number += 1

            elif force:
                # statement with a block: needs a true newline before it
                self.force_newline = True
                self.new_lines += node.lineno - self.line_number
                self.line_number = node.lineno

            else:
                # block-less statement: needs a semicolon, colon, or newline in front of it
                self.new_lines += node.lineno - self.line_number
                self.line_number = node.lineno

    def maybe_break(self, node):
        if self.correct_line_numbers:
            self.new_lines += node.lineno - self.line_number
            self.line_number = node.lineno

    def body(self, statements):
        self.force_newline = any(isinstance(i, self.BLOCK_NODES) for i in statements)
        self.indentation += 1
        self.after_colon = 1
        for stmt in statements:
            self.visit(stmt)
        self.indentation -= 1
        self.force_newline = True
        self.after_colon = 0 # do empty blocks even exist?

    def body_or_else(self, node):
        self.body(node.body)
        if node.orelse:
            self.newline()
            self.write('else:')
            self.body(node.orelse)

    def visit_bare(self, node):
        # this node is allowed to be a bare tuple
        if isinstance(node, Tuple):
            self.visit_Tuple(node, False)
        else:
            self.visit(node)

    def visit_bareyield(self, node):
        if isinstance(node, Yield):
            self.visit_Yield(node, False)
        elif isinstance(node, YieldFrom):
            self.visit_YieldFrom(node, False)
        else:
            self.visit_bare(node)

    def decorators(self, node):
        for decorator in node.decorator_list:
            self.newline(decorator, force=True)
            self.write('@')
            self.visit(decorator)
        if node.decorator_list:
            self.newline()
        else:
            self.newline(node, force=True)

    # Module
    def visit_Module(self, node):
        self.generic_visit(node)
        self.write('\n')
        self.line_number += 1

    # Statements

    def visit_Assert(self, node):
        self.newline(node)
        self.write('assert ')
        self.visit(node.test)
        if node.msg:
            self.write(self.COMMA)
            self.visit(node.msg)

    def visit_Assign(self, node):
        self.newline(node)
        for target in node.targets:
            self.visit_bare(target)
            self.write(self.ASSIGN)
        self.visit_bareyield(node.value)

    def visit_AugAssign(self, node):
        self.newline(node)
        self.visit_bare(node.target)
        self.write(self.BINOP_SYMBOLS[type(node.op)][0].rstrip() + self.ASSIGN.lstrip())
        self.visit_bareyield(node.value)

    def visit_Await(self, node):
        self.maybe_break(node)
        self.prec_start(16, True)
        self.prec_middle()
        self.write('await ')
        self.visit(node.value)
        self.prec_end()

    def visit_ImportFrom(self, node):
        self.newline(node)
        self.write('from ')
        self.write('%s%s' % ('.' * node.level, node.module or ''))
        self.write(' import ')
        sep = Sep(self.COMMA)
        for item in node.names:
            self.write(sep())
            self.visit(item)

    def visit_Import(self, node):
        self.newline(node)
        self.write('import ')
        sep = Sep(self.COMMA)
        for item in node.names:
            self.write(sep())
            self.visit(item)

    def visit_Exec(self, node):
        self.newline(node)
        self.write('exec ')
        self.visit(node.body)
        if node.globals:
            self.write(' in ')
            self.visit(node.globals)
        if node.locals:
            self.write(self.COMMA)
            self.visit(node.locals)

    def visit_Expr(self, node):
        self.newline(node)
        self.visit_bareyield(node.value)

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node, True)

    def visit_FunctionDef(self, node, async=False):
        self.newline(extra=1)
        # first decorator line number will be used
        self.decorators(node)
        if async:
            self.write('async ')
        self.write('def ')
        self.write(node.name)
        self.paren_start()
        self.visit_arguments(node.args)
        self.paren_end()
        if hasattr(node, 'returns') and node.returns is not None:
            self.write(self.ARROW)
            self.visit(node.returns)
        self.write(':')
        self.body(node.body)

    def visit_arguments(self, node):
        sep = Sep(self.COMMA)
        padding = [None] * (len(node.args) - len(node.defaults))
        if hasattr(node, 'kwonlyargs'):
            for arg, default in zip(node.args, padding + node.defaults):
                self.write(sep())
                self.visit(arg)
                if default is not None:
                    self.write('=')
                    self.visit(default)
            if node.vararg is not None:
                self.write(sep())
                if hasattr(node, 'varargannotation'):
                    if node.varargannotation is None:
                        self.write('*' + node.vararg)
                    else:
                        self.maybe_break(node.varargannotation)
                        self.write('*' + node.vararg)
                        self.write(self.COLON)
                        self.visit(node.varargannotation)
                else:
                    self.maybe_break(node.vararg)
                    self.write('*')
                    self.visit(node.vararg)
            elif node.kwonlyargs:
                self.write(sep() + '*')

            for arg, default in zip(node.kwonlyargs, node.kw_defaults):
                self.write(sep())
                self.visit(arg)
                if default is not None:
                    self.write('=')
                    self.visit(default)
            if node.kwarg is not None:
                self.write(sep())
                if hasattr(node, 'kwargannotation'):
                    if node.kwargannotation is None:
                        self.write('**' + node.kwarg)
                    else:
                        self.maybe_break(node.kwargannotation)
                        self.write('**' + node.kwarg)
                        self.write(self.COLON)
                        self.visit(node.kwargannotation)
                else:
                    self.maybe_break(node.kwarg)
                    self.write('**')
                    self.visit(node.kwarg)
        else:
            for arg, default in zip(node.args, padding + node.defaults):
                self.write(sep())
                self.visit(arg)
                if default is not None:
                    self.write('=')
                    self.visit(default)
            if node.vararg is not None:
                self.write(sep())
                self.write('*' + node.vararg)
            if node.kwarg is not None:
                self.write(sep())
                self.write('**' + node.kwarg)

    def visit_arg(self, node):
        # Py3 only
        self.maybe_break(node)
        self.write(node.arg)
        if node.annotation is not None:
            self.write(self.COLON)
            self.visit(node.annotation)

    def visit_keyword(self, node):
        self.maybe_break(node.value)
        if node.arg is not None:
            self.write(node.arg + '=')
        else:
            self.write('**')
        self.visit(node.value)

    def visit_ClassDef(self, node):
        self.newline(extra=2)
        # first decorator line number will be used
        self.decorators(node)
        self.write('class %s' % node.name)

        if (node.bases or (hasattr(node, 'keywords') and node.keywords) or
                (hasattr(node, 'starargs') and (node.starargs or node.kwargs))):
            self.paren_start()
            sep = Sep(self.COMMA)

            for base in node.bases:
                self.write(sep())
                self.visit(base)
            # XXX: the if here is used to keep this module compatible
            #      with python 2.6.
            if hasattr(node, 'keywords'):
                for keyword in node.keywords:
                    self.write(sep())
                    self.visit(keyword)
                if hasattr(node, 'starargs'):
                    if node.starargs is not None:
                        self.write(sep())
                        self.maybe_break(node.starargs)
                        self.write('*')
                        self.visit(node.starargs)
                    if node.kwargs is not None:
                        self.write(sep())
                        self.maybe_break(node.kwargs)
                        self.write('**')
                        self.visit(node.kwargs)
            self.paren_end()
        self.write(':')
        self.body(node.body)

    def visit_If(self, node):
        self.newline(node, force=True)
        self.write('if ')
        self.visit(node.test)
        self.write(':')
        self.body(node.body)
        while True:
            if len(node.orelse) == 1 and isinstance(node.orelse[0], If):
                node = node.orelse[0]
                self.newline(node.test, force=True)
                self.write('elif ')
                self.visit(node.test)
                self.write(':')
                self.body(node.body)
            else:
                if node.orelse:
                    self.newline()
                    self.write('else:')
                    self.body(node.orelse)
                break

    def visit_AsyncFor(self, node):
        self.visit_For(node, True)

    def visit_For(self, node, async=False):
        self.newline(node, force=True)
        if async:
            self.write('async ')
        self.write('for ')
        self.visit_bare(node.target)
        self.write(' in ')
        self.visit(node.iter)
        self.write(':')
        self.body_or_else(node)

    def visit_While(self, node):
        self.newline(node, force=True)
        self.write('while ')
        self.visit(node.test)
        self.write(':')
        self.body_or_else(node)

    def visit_AsyncWith(self, node):
        self.visit_With(node, True)

    def visit_With(self, node, async=False):
        self.newline(node, force=True)
        if async:
            self.write('async ')
        self.write('with ')

        if hasattr(node, 'items'):
            sep = Sep(self.COMMA)
            for item in node.items:
                self.write(sep())
                self.visit_withitem(item)
        else:
            # in python 2, similarly to the elif statement, multiple nested context managers
            # are generally the multi-form of a single with statement
            self.visit_withitem(node)
            while len(node.body) == 1 and isinstance(node.body[0], With):
                node = node.body[0]
                self.write(self.COMMA)
                self.visit_withitem(node)
        self.write(':')
        self.body(node.body)

    def visit_withitem(self, node):
        self.visit(node.context_expr)
        if node.optional_vars is not None:
            self.write(' as ')
            self.visit(node.optional_vars)

    def visit_Pass(self, node):
        self.newline(node)
        self.write('pass')

    def visit_Print(self, node):
        # XXX: python 2 only
        self.newline(node)
        self.write('print ')
        sep = Sep(self.COMMA)
        if node.dest is not None:
            self.write(' >> ')
            self.visit(node.dest)
            sep()
        for value in node.values:
            self.write(sep())
            self.visit(value)
        if not node.nl:
            self.write(',')

    def visit_Delete(self, node):
        self.newline(node)
        self.write('del ')
        sep = Sep(self.COMMA)
        for target in node.targets:
            self.write(sep())
            self.visit(target)

    def visit_Try(self, node):
        # Python 3 only. exploits the fact that TryExcept uses the same attribute names
        self.visit_TryExcept(node)
        if node.finalbody:
            self.newline()
            self.write('finally:')
            self.body(node.finalbody)

    def visit_TryExcept(self, node):
        self.newline(node, force=True)
        self.write('try:')
        self.body(node.body)
        for handler in node.handlers:
            self.visit(handler)
        if node.orelse:
            self.newline()
            self.write('else:')
            self.body(node.orelse)

    def visit_TryFinally(self, node):
        # Python 2 only
        if len(node.body) == 1 and isinstance(node.body[0], TryExcept):
            self.visit_TryExcept(node.body[0])
        else:
            self.newline(node, force=True)
            self.write('try:')
            self.body(node.body)
        self.newline()
        self.write('finally:')
        self.body(node.finalbody)

    def visit_ExceptHandler(self, node):
        self.newline(node, force=True)
        self.write('except')
        if node.type:
            self.write(' ')
            self.visit(node.type)
            if node.name:
                self.write(' as ')
                # Compatability
                if isinstance(node.name, AST):
                    self.visit(node.name)
                else:
                    self.write(node.name)
        self.write(':')
        self.body(node.body)

    def visit_Global(self, node):
        self.newline(node)
        self.write('global ' + self.COMMA.join(node.names))

    def visit_Nonlocal(self, node):
        self.newline(node)
        self.write('nonlocal ' + self.COMMA.join(node.names))

    def visit_Return(self, node):
        self.newline(node)
        if node.value is not None:
            self.write('return ')
            self.visit(node.value)
        else:
            self.write('return')

    def visit_Break(self, node):
        self.newline(node)
        self.write('break')

    def visit_Continue(self, node):
        self.newline(node)
        self.write('continue')

    def visit_Raise(self, node):
        # XXX: Python 2.6 / 3.0 compatibility
        self.newline(node)
        if hasattr(node, 'exc') and node.exc is not None:
            self.write('raise ')
            self.visit(node.exc)
            if node.cause is not None:
                self.write(' from ')
                self.visit(node.cause)
        elif hasattr(node, 'type') and node.type is not None:
            self.write('raise ')
            self.visit(node.type)
            if node.inst is not None:
                self.write(self.COMMA)
                self.visit(node.inst)
            if node.tback is not None:
                self.write(self.COMMA)
                self.visit(node.tback)
        else:
            self.write('raise')

    # Expressions

    def visit_Attribute(self, node):
        self.maybe_break(node)
        # Edge case: due to the use of \d*[.]\d* for floats \d*[.]\w*, you have
        # to put parenthesis around an integer literal do get an attribute from it
        if isinstance(node.value, Num):
            self.paren_start()
            self.visit(node.value)
            self.paren_end()
        else:
            self.prec_start(17)
            self.visit(node.value)
            self.prec_end()
        self.write('.' + node.attr)

    def visit_Call(self, node):
        self.maybe_break(node)
        #need to put parenthesis around numbers being called (this makes no sense)
        if isinstance(node.func, Num):
            self.paren_start()
            self.visit_Num(node.func)
            self.paren_end()
        else:
            self.prec_start(17)
            self.visit(node.func)
            self.prec_end()
        # special case generator expressions as only argument
        if (len(node.args) == 1 and isinstance(node.args[0], GeneratorExp) and
                not node.keywords and hasattr(node, 'starargs') and
                not node.starargs and not node.kwargs):
            self.visit_GeneratorExp(node.args[0])
            return

        self.paren_start()
        sep = Sep(self.COMMA)
        for arg in node.args:
            self.write(sep())
            self.maybe_break(arg)
            self.visit(arg)
        for keyword in node.keywords:
            self.write(sep())
            self.visit(keyword)
        if hasattr(node, 'starargs'):
            if node.starargs is not None:
                self.write(sep())
                self.maybe_break(node.starargs)
                self.write('*')
                self.visit(node.starargs)
            if node.kwargs is not None:
                self.write(sep())
                self.maybe_break(node.kwargs)
                self.write('**')
                self.visit(node.kwargs)
        self.paren_end()

    def visit_Name(self, node):
        self.maybe_break(node)
        self.write(node.id)

    def visit_NameConstant(self, node):
        self.maybe_break(node)
        self.write(repr(node.value))

    def visit_Str(self, node, frombytes=False):
        self.maybe_break(node)
        if frombytes:
            newline_count = node.s.count('\n'.encode('utf-8'))
        else:
            newline_count = node.s.count('\n')

        # heuristic, expand when more than 1 newline and when at least 80%
        # of the characters aren't newlines
        expand = newline_count > 1 and len(node.s) > 5 * newline_count
        if self.correct_line_numbers:
            # Also check if we have enougn newlines to expand in if we're going for correct line numbers
            if self.after_colon:
                # Although this makes little sense just after a colon
                expand = expand and self.new_lines > newline_count
            else:
                expand = expand and self.new_lines >= newline_count

        if expand and (not self.correct_line_numbers or self.new_lines >= newline_count):
            if self.correct_line_numbers:
                self.new_lines -= newline_count

            a = repr(node.s)
            delimiter = a[-1]
            header, content = a[:-1].split(delimiter, 1)
            lines = []
            chain = False
            for i in content.split('\\n'):
                if chain:
                    i = lines.pop() + i
                    chain = False
                if (len(i) - len(i.rstrip('\\'))) % 2:
                    i += '\\n'
                    chain = True
                lines.append(i)
            assert newline_count + 1 == len(lines)
            self.write(header)
            self.write(delimiter * 3)
            self.write('\n'.join(lines))
            self.write(delimiter * 3)
        else:
            self.write(repr(node.s))

    def visit_Bytes(self, node):
        self.visit_Str(node, True)

    def visit_Num(self, node):
        self.maybe_break(node)

        negative = (node.n.imag or node.n.real) < 0 and not PY3
        if negative:
            self.prec_start(self.UNARYOP_SYMBOLS[USub][1])

        # 1e999 and related friends are parsed into inf
        if abs(node.n) == 1e999:
            if negative:
                self.write('-')
            self.write('1e999')
            if node.n.imag:
                self.write('j')
        else:
            self.write(repr(node.n))

        if negative:
            self.prec_end()

    def visit_Tuple(self, node, guard=True):
        if guard or not node.elts:
            self.paren_start()
        sep = Sep(self.COMMA)
        for item in node.elts:
            self.write(sep())
            self.visit(item)
        if len(node.elts) == 1:
            self.write(',')
        if guard or not node.elts:
            self.paren_end()

    def _sequence_visit(left, right): # pylint: disable=E0213
        def visit(self, node):
            self.maybe_break(node)
            self.paren_start(left)
            sep = Sep(self.COMMA)
            for item in node.elts:
                self.write(sep())
                self.visit(item)
            self.paren_end(right)
        return visit

    visit_List = _sequence_visit('[', ']')
    visit_Set = _sequence_visit('{', '}')

    def visit_Dict(self, node):
        self.maybe_break(node)
        self.paren_start('{')
        sep = Sep(self.COMMA)
        for key, value in zip(node.keys, node.values):
            self.write(sep())
            self.visit(key)
            self.write(self.COLON)
            self.visit(value)
        self.paren_end('}')

    def visit_BinOp(self, node):
        self.maybe_break(node)
        symbol, precedence = self.BINOP_SYMBOLS[type(node.op)]
        self.prec_start(precedence, type(node.op) != Pow)

        # work around python's negative integer literal optimization
        if isinstance(node.op, Pow):
            self.visit(node.left)
            self.prec_middle(14)
        else:
            self.visit(node.left)
            self.prec_middle()
        self.write(symbol)
        self.visit(node.right)
        self.prec_end()

    def visit_BoolOp(self, node):
        self.maybe_break(node)
        symbol, precedence = self.BOOLOP_SYMBOLS[type(node.op)]
        self.prec_start(precedence, True)
        self.prec_middle()
        sep = Sep(symbol)
        for value in node.values:
            self.write(sep())
            self.visit(value)
        self.prec_end()

    def visit_Compare(self, node):
        self.maybe_break(node)
        self.prec_start(7, True)
        self.prec_middle()
        self.visit(node.left)
        for op, right in zip(node.ops, node.comparators):
            self.write(self.CMPOP_SYMBOLS[type(op)][0])
            self.visit(right)
        self.prec_end()

    def visit_UnaryOp(self, node):
        self.maybe_break(node)
        symbol, precedence = self.UNARYOP_SYMBOLS[type(node.op)]
        self.prec_start(precedence)
        self.write(symbol)
        # workaround: in python 2, an explicit USub node around a number literal
        # indicates the literal was surrounded by parenthesis
        if (not PY3 and isinstance(node.op, USub) and isinstance(node.operand, Num)
                and (node.operand.n.real or node.operand.n.imag) >= 0):
            self.paren_start()
            self.visit(node.operand)
            self.paren_end()
        else:
            self.visit(node.operand)
        self.prec_end()

    def visit_Subscript(self, node):
        self.maybe_break(node)
        # have to surround literals by parenthesis (at least in Py2)
        if isinstance(node.value, Num):
            self.paren_start()
            self.visit_Num(node.value)
            self.paren_end()
        else:
            self.prec_start(17)
            self.visit(node.value)
            self.prec_end()
        self.paren_start('[')
        self.visit(node.slice)
        self.paren_end(']')

    def visit_Index(self, node, guard=False):
        # Index has no lineno information
        # When a subscript includes a tuple directly, the parenthesis can be dropped
        if not guard:
            self.visit_bare(node.value)
        else:
            self.visit(node.value)

    def visit_Slice(self, node):
        # Slice has no lineno information
        if node.lower is not None:
            self.visit(node.lower)
        self.write(':')
        if node.upper is not None:
            self.visit(node.upper)
        if node.step is not None:
            self.write(':')
            if not (isinstance(node.step, Name) and node.step.id == 'None'):
                self.visit(node.step)

    def visit_Ellipsis(self, node):
        # Ellipsis has no lineno information
        self.write('...')

    def visit_ExtSlice(self, node):
        # Extslice has no lineno information
        for idx, item in enumerate(node.dims):
            if idx:
                self.write(self.COMMA)
            if isinstance(item, Index):
                self.visit_Index(item, True)
            else:
                self.visit(item)

    def visit_Yield(self, node, paren=True):
        # yield can only be used in a statement context, or we're between parenthesis
        self.maybe_break(node)
        if paren:
            self.paren_start()
        if node.value is not None:
            self.write('yield ')
            self.visit_bare(node.value)
        else:
            self.write('yield')
        if paren:
            self.paren_end()

    def visit_YieldFrom(self, node, paren=True):
        # Even though yield and yield from technically occupy precedence level 1, certain code
        # using them is illegal e.g. "return yield from a()" will not work unless you
        # put the yield from statement within parenthesis.
        self.maybe_break(node)
        if paren:
            self.paren_start()
        self.write('yield from ')
        self.visit(node.value)
        if paren:
            self.paren_end()

    def visit_Lambda(self, node):
        self.maybe_break(node)
        self.prec_start(2)
        self.write('lambda ')
        self.visit_arguments(node.args)
        self.write(self.COLON)
        self.visit(node.body)
        self.prec_end()

    def _generator_visit(left, right):
        def visit(self, node):
            self.maybe_break(node)
            self.paren_start(left)
            self.visit(node.elt)
            for comprehension in node.generators:
                self.visit(comprehension)
            self.paren_end(right)
        return visit

    visit_ListComp = _generator_visit('[', ']')
    visit_GeneratorExp = _generator_visit('(', ')')
    visit_SetComp = _generator_visit('{', '}')

    def visit_DictComp(self, node):
        self.maybe_break(node)
        self.paren_start('{')
        self.visit(node.key)
        self.write(self.COLON)
        self.visit(node.value)
        for comprehension in node.generators:
            self.visit(comprehension)
        self.paren_end('}')

    def visit_IfExp(self, node):
        self.maybe_break(node)
        self.prec_start(3, False)
        self.visit(node.body)
        self.write(' if ')
        self.visit(node.test)
        self.prec_middle(2)
        self.write(' else ')
        self.visit(node.orelse)
        self.prec_end()

    def visit_Starred(self, node):
        self.maybe_break(node)
        self.write('*')
        self.visit(node.value)

    def visit_Repr(self, node):
        # XXX: python 2.6 only
        self.maybe_break(node)
        self.write('`')
        self.visit(node.value)
        self.write('`')

    # Helper Nodes

    def visit_alias(self, node):
        # alias does not have line number information
        self.write(node.name)
        if node.asname is not None:
            self.write(' as ' + node.asname)

    def visit_comprehension(self, node):
        self.maybe_break(node.target)
        self.write(' for ')
        self.visit_bare(node.target)
        self.write(' in ')
        # workaround: lambda and ternary need to be within parenthesis here
        self.prec_start(4)
        self.visit(node.iter)
        self.prec_end()

        for if_ in node.ifs:
            self.write(' if ')
            self.visit(if_)
