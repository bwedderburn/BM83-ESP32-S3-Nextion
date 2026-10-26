#!/usr/bin/perl
# Load the read-only snapshot helper in the Apple-signed system Perl host.
# This uses the public DynaLoader loading pattern, as demonstrated by
# https://github.com/ungive/mediaremote-adapter (BSD-3-Clause).
use strict;
use warnings;
use DynaLoader;
use Cwd qw(abs_path);

@ARGV == 1 or die "Usage: read_now_playing.pl /absolute/path/now_playing.dylib\n";
my $path = abs_path($ARGV[0]) or die "Snapshot helper not found\n";
my $handle = DynaLoader::dl_load_file($path, 0) or die "Cannot load snapshot helper\n";
my $symbol = DynaLoader::dl_find_symbol($handle, 'bm83_now_playing') or die "Snapshot entry point missing\n";
DynaLoader::dl_install_xsub('main::snapshot', $symbol);
snapshot();
