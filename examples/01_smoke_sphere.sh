% Sphere of water, 14 MeV point source - smoke test, Serpent 2.1.32
% Run: sss2 01_smoke_sphere.sh -noplot -norun   (paths relative to run dir)
set title "smoke: H2O sphere"

surf s_sph sph 0 0 0 10
surf s_out sph 0 0 0 500

cell c_w 0 H2O -s_sph
cell c_v 0 void -s_out s_sph
cell c_o 0 outside s_out

mat H2O -1
H-1.03c 2
O-16.03c 1

src s1 n sp 0 0 0 se 14.0

ene e 4 scale44
det flx dm H2O de e

set nps 2000 20
set bc 1
set acelib "xsdata/data.xsdata"
