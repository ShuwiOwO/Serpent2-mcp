# `set` и карты 2.1.32 — рабочий минимум (из эталонов HW1..HW6)

Полный синтаксис — официальная дока VTT. Здесь только то, что реально используется
в golden-наборе, с ловушками 2.1.32.

## `src` (источник)

```
src NAME [n|p] [sw W] [sm MAT] [sp X Y Z] [srad RMIN RMAX]
    [sd U V W] [sa PHI] [se E] [sb NE INTT E1 F1 ...] [sg DMAT MODE]
```

- `sg DMAT MODE`: `DMAT=-1` = все радиоактивные материалы; `MODE 1` = analog (физ. интенсивности), `2` = implicit. Требует `set declib`; нейтроны спонтанного деления — ещё `set nfylib`.
- `sb NE INTT ...`: `NE` = число точек; `INTT 1` = histogram. Энергии по возрастанию, МэВ, нормируются сами.
- `se E`: моноэнергия МэВ; `se 1` + `sd 1 0 0` = импульс HW4; Pu-Be в HW6 — средняя 4.84 МэВ (табличный `sb`, не `se`).
- `sp/srad/sm`: точка/шар/объём материала. Несколько `src` взвешиваются `sw`.
- Продолжение: строки `sb`-спектра принадлежат карте `src` до следующей зарезервированной карты.

## `det` (детектор)

```
det NAME [n|p] [dv VOL] [dc CELL] [dm MAT] [dr MT RMAT] [de EGRID] [di TBIN]
```

- `dr -11 void` — спектр излучения источника (для построения `sb`).
- `dr -200 void` — доза на человеке (HW2/HW5 эталоны).
- `dr -100 NAME` — только с `fun NAME ...`, иначе ошибка входа.
- `de EGRID` — только имя `ene`-сетки, предопределённую (`scale44`) напрямую нельзя.
- `di TBIN` — только имя `tme`-сетки.
- Результат — интеграл по объёму, не среднее. `dv` обязателен для `dm` при нормировке.

## `ene` / `tme` / `fun`

```
ene e 4 scale44
tme TB 2 100 0 0.1
fun NAME INTT X1 F1 X2 F2 ...
```

- `ene TYPE 4` = встроенная структура (`scale44/56/238`, `_ext` — на все энергии).
- `tme TYPE 2` = равномерные бины (`N Tmin Tmax`).

## `wwgen` / `wwin` (HW5)

```
wwgen GENA 1E-12 4 3 -1 1
    -210 35 30
    -45 45 30
    -110 110 30
wwin WIN
    wi 1 5
        GENA 1 (x5)
```

`LIM=1E-12`, `NI=4`, `MOD=3` (GVR), `ERG=-1`, `MSH=1` (декартова). Даёт `.wwd*`.

## `mat` / `therm`

```
mat curium -13.5 vol 0.5
Cm-250 1
mat H2O -1
H-nat.84p 2
O-nat.84p 1
therm grap gre7.00t
mat gr sum moder grap 6000
6000.03c 0.08363
```

- Грязный графит HW4: `+ 5010.03c 1.83E-7, 5011.03c 7.46E-7`.
- `.00t` записи живут в `data.xsdata` и указывают в `acedata/sssth1` (файл, не каталог).

## `set` (частые)

| Опция | Пример | Заметка 2.1.32 |
|---|---|---|
| `title` | `set title "case"` | |
| `acelib` | `set acelib "xsdata/data.xsdata"` | обязателен без `SERPENT_ACELIB` |
| `declib/nfylib` | `set declib "xsdata/jef3.dec"` | `jef3` = JEFF-3.3; нейтронам нужен ещё `nfylib` |
| `pdatadir` | `set pdatadir "xsdata/photon_data"` | 11×`.dat`; `photon_data/data.xsdata` игнорировать |
| `nps` | `set nps 10000 100` | внешний источник; `pop` и `nps` взаимоисключают |
| `pop` | `set pop 5000 100 20` | критичность (в HW-наборе не основная) |
| `bc` | `set bc 1` | 1=чёрная, 2=отражательная, 3=периодическая |
| `srcrate/power` | `set srcrate 1.03E11` | `tot` из `_gsrc/_nsrc` |
| `mvol` | `set mvol ...` | объёмы для burnup (в HW1..6 не ключевое) |

Зарезервированные имена (нельзя использовать как идентификаторы): `branch casematrix cell coef datamesh dep det div ene fun hisv ifc include lat mat mesh mflow mix nest particle pbed pin plot rep sample sens set solid src surf therm tme trans umsh voro wwgen wwin`.
