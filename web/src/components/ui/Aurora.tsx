/* The moving coloured background of the Aurora theme: four blurred halos drifting slowly behind
   the glass cards. Pure CSS (globals.css), fixed, behind everything; still with reduced motion. */
export function Aurora() {
  return (
    <div aria-hidden className="aurora">
      <span className="a1" /><span className="a2" /><span className="a3" /><span className="a4" />
    </div>
  );
}
