.PHONY:pre all
SRCS:=$(wildcard frames/*.dot)
OBJS:=$(patsubst %.dot,%.png,$(SRCS))

paths.gif: $(OBJS)
	convert -delay 20 -loop 0 frames/*.png $@

pre:
	./h1-to-h9-path.py

$(SRCS):
	./h1-to-h9-path.py

frames/h1-to-h9-%.png: frames/h1-to-h9-%.dot
	dot $< -Tpng -o $@

clean:
	rm frames/*

